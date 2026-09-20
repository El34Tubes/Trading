from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
import uuid

import pytest

from test_db import test_connection


def _publishable_readiness(signal_dt: date):
    from eod_readiness import EODReadiness, SourceMode

    return EODReadiness(
        expected_session=signal_dt,
        latest_complete_session=signal_dt,
        coverage_numerator=3,
        coverage_denominator=3,
        missing_symbols=(),
        source_mode=SourceMode.FREE_T_PLUS_1,
        publishable=True,
    )


def test_replay_readiness_requires_historical_pivot_snapshot(monkeypatch):
    import orchestration_runner

    captured = {}

    def fake_evaluate(conn, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("eod_readiness.evaluate_eod_readiness", fake_evaluate)
    decision_at = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
    result = orchestration_runner.evaluate_replay_eod_readiness(
        object(),
        tickers=("SHOULD_NOT_DEFINE_SNAPSHOT_MEMBERS",),
        signal_dt=date(2026, 8, 18),
        decision_at=decision_at,
    )

    assert result is not None
    assert captured["expected_session"] == date(2026, 8, 18)
    assert captured["decision_at"] == decision_at
    assert captured["require_universe_snapshot"] is True
    assert captured["universe"] == ()


def test_paper_recommendation_lifecycle_writes_and_logs_approved_signal_without_broker_action():
    from orchestration_runner import run_paper_recommendation_lifecycle

    strategy_name = "unit_paper_recommendation_lifecycle"
    ticker = "ZZRLC"
    signal_dt = date(2099, 3, 2)
    metadata = {
        "approval_scope": "paper_only_no_live_execution",
        "paper_recommendation_approval": True,
        "paper_entry_baseline": "eod_close",
        "max_paper_recs_per_day": 3,
        "risk_per_trade_fraction": 0.05,
    }
    with test_connection() as conn:
        conn.execute("DELETE FROM paper_trades WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM recommendations WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM signals WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM strategies WHERE name=%s", (strategy_name,))
        strategy_id = conn.execute(
            """
            INSERT INTO strategies(name,setup_type,status,latest_oos_verdict,last_validated,metadata)
            VALUES (%s,'unit','approved',true,%s,%s::jsonb) RETURNING id
            """,
            (strategy_name, signal_dt, json.dumps(metadata)),
        ).fetchone()[0]
        raw = {
            "strategy": strategy_name,
            "close": "100",
            "invalidation": "99",
            "prior_5d_high": "99",
            "target_r": "1.0",
            "stop_rule": "close_below_breakout_level",
            "rs_excess_20d": "0.05",
            "vol_ratio": "1.8",
        }
        conn.execute(
            "INSERT INTO signals(ticker,dt,strategy_id,direction,raw) VALUES (%s,%s,%s,'long',%s::jsonb)",
            (ticker, signal_dt, strategy_id, json.dumps(raw)),
        )

        result = run_paper_recommendation_lifecycle(
            conn,
            signal_dt=signal_dt,
            tickers=[ticker],
            as_of=signal_dt,
        )
        row = conn.execute(
            """
            SELECT r.status,r.notes,pt.status,pt.notes
            FROM recommendations r
            JOIN paper_trades pt ON pt.recommendation_id=r.id::text
            WHERE r.ticker=%s
            """,
            (ticker,),
        ).fetchone()

        conn.execute("DELETE FROM paper_trades WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM recommendations WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM signals WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM strategies WHERE id=%s", (strategy_id,))

    assert result["recommendations"]["recommendations_created"] == 1
    assert result["paper_trades"]["paper_trades_created"] == 1
    assert result["outcomes"]["closed_trades"] == 0
    assert result["broker_orders_created"] == 0
    assert row[0] == "paper_logged"
    assert row[1]["no_live_execution"] is True
    assert row[1]["broker_order_submitted"] is False
    assert row[2] == "open"
    assert row[3]["no_live_execution"] is True
    assert row[3]["broker_order_submitted"] is False


def test_eod_signal_runner_invokes_paper_lifecycle_after_success(monkeypatch):
    import orchestration_runner

    captured = {}

    def fake_signal_call(cmd):
        captured["cmd"] = cmd
        return 0

    def fake_lifecycle(conn, *, signal_dt, tickers, as_of=None, max_recommendations=20, dry_run=False):
        captured["lifecycle"] = {
            "signal_dt": signal_dt,
            "tickers": tickers,
            "as_of": as_of,
            "max_recommendations": max_recommendations,
            "dry_run": dry_run,
        }
        return {"broker_orders_created": 0, "no_live_execution": True}

    monkeypatch.setattr(orchestration_runner.subprocess, "call", fake_signal_call)
    monkeypatch.setattr(orchestration_runner, "run_paper_recommendation_lifecycle", fake_lifecycle)
    monkeypatch.setattr(
        orchestration_runner,
        "evaluate_replay_eod_readiness",
        lambda conn, *, tickers, signal_dt: _publishable_readiness(signal_dt),
    )

    rc = orchestration_runner.run_eod_features_signals(
        tickers_csv_value="SPY",
        signal_dt_value="2026-08-18",
    )

    assert rc == 0
    assert "--create-setups" in captured["cmd"]
    assert captured["lifecycle"]["signal_dt"] == date(2026, 8, 18)
    assert captured["lifecycle"]["tickers"] == ["SPY"]
    assert captured["lifecycle"]["as_of"] == date(2026, 8, 18)
    assert captured["lifecycle"]["max_recommendations"] == 20
    assert captured["lifecycle"]["dry_run"] is False


def test_eod_signal_runner_stops_before_paper_lifecycle_on_signal_failure(monkeypatch):
    import orchestration_runner

    lifecycle_called = False

    def fake_lifecycle(*args, **kwargs):
        nonlocal lifecycle_called
        lifecycle_called = True
        raise AssertionError("paper lifecycle must not run after signal failure")

    monkeypatch.setattr(orchestration_runner.subprocess, "call", lambda cmd: 7)
    monkeypatch.setattr(orchestration_runner, "run_paper_recommendation_lifecycle", fake_lifecycle)
    monkeypatch.setattr(
        orchestration_runner,
        "evaluate_replay_eod_readiness",
        lambda conn, *, tickers, signal_dt: _publishable_readiness(signal_dt),
    )

    rc = orchestration_runner.run_eod_features_signals(
        tickers_csv_value="SPY",
        signal_dt_value="2026-08-18",
    )

    assert rc == 7
    assert lifecycle_called is False


def test_mid_small_shadow_runner_uses_persisted_candidates_and_never_invokes_writer(monkeypatch):
    import orchestration_runner
    from daily_multi_strategy import SHADOW_STAGE_NAMES
    from eod_readiness import EODReadiness, SourceMode
    from option_chain_provider import OptionChainProviderUnavailable
    from portfolio_allocator import PortfolioCandidate

    snapshot_id = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    run_id = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    signal_dt = date(2099, 5, 1)
    candidate = PortfolioCandidate(
        candidate_id=uuid.uuid4(),
        universe_snapshot_id=snapshot_id,
        ticker="ZZORCH",
        strategy_id="liquid_rs_breakout_close_confirm_1r",
        strategy_version="approved-2026-08-03",
        sector="Industrials",
        score=Decimal("2"),
        entry=Decimal("20"),
        stop=Decimal("19"),
        target=Decimal("22"),
    )
    readiness = EODReadiness(
        expected_session=signal_dt,
        latest_complete_session=signal_dt,
        coverage_numerator=4,
        coverage_denominator=4,
        missing_symbols=(),
        source_mode=SourceMode.FREE_T_PLUS_1,
        publishable=True,
        universe_snapshot_id=str(snapshot_id),
        universe_policy_version="mid_small_multi_strategy_pivot_v1",
        universe_source_fingerprint="a" * 64,
        benchmark_coverage_numerator=3,
        benchmark_coverage_denominator=3,
        member_coverage_numerator=1,
        member_coverage_denominator=1,
    )
    monkeypatch.setattr(
        orchestration_runner,
        "load_mid_small_portfolio_candidates",
        lambda conn, selected_run_id: (candidate,),
    )
    monkeypatch.setattr(
        orchestration_runner,
        "load_mid_small_existing_positions",
        lambda conn: (),
    )

    result = orchestration_runner.run_mid_small_shadow_orchestrator(
        object(),
        run_id=run_id,
        signal_dt=signal_dt,
        decision_at=datetime(2099, 5, 2, tzinfo=timezone.utc),
        readiness=readiness,
        account_equity=Decimal("10000"),
        chain_acquirer=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OptionChainProviderUnavailable("offline")
        ),
    )

    assert result.status == "shadow_complete"
    assert result.stage_names == SHADOW_STAGE_NAMES
    assert result.instrument_decisions[0].expression == "underlying_stock_fallback"
    assert result.recommendations_created == 0
    assert result.broker_orders_created == 0
    assert result.external_deliveries == 0


def test_mid_small_shadow_cli_accepts_only_bounded_shadow_controls():
    from orchestration_runner import parse_mid_small_shadow_args

    args = parse_mid_small_shadow_args(
        [
            "--shadow",
            "--dry-run",
            "--signal-dt",
            "2099-05-01",
            "--strategy",
            "trend_pullback_reclaim",
            "--tickers",
            "AAA,BBB",
        ]
    )

    assert args.shadow is True
    assert args.dry_run is True
    assert args.signal_dt == "2099-05-01"
    assert args.strategy == ["trend_pullback_reclaim"]
    assert args.tickers == "AAA,BBB"


def _approved_shadow_release(snapshot: str):
    from shadow_pivot_report import ShadowReleaseReport

    return ShadowReleaseReport(
        snapshot_fingerprint=snapshot,
        approved=True,
        task23_preflight_eligible=True,
        production_activation_authorized=False,
        production_baselines_unchanged=True,
        failure_reasons=(),
        replay_scenarios=(
            "ordinary",
            "no_signal",
            "chain_unavailable",
            "sector_concentrated",
            "near_cap",
        ),
    )


def test_paper_canary_preflight_requires_explicit_exact_release_and_breakout_only(monkeypatch):
    import orchestration_runner

    from orchestration_runner import (
        MID_SMALL_PAPER_RELEASE_CONFIG_VERSION,
        PaperCanaryGateError,
        authorize_mid_small_paper_canary,
    )

    snapshot = "a" * 64
    report = _approved_shadow_release(snapshot)
    kwargs = {
        "shadow_report": report,
        "snapshot_fingerprint": snapshot,
        "release_enabled": True,
        "config_version": MID_SMALL_PAPER_RELEASE_CONFIG_VERSION,
        "strategies": ("close_confirmed_breakout",),
        "publisher_count": 1,
        "rollback_command": "restore_previous_publisher",
    }

    with pytest.raises(PaperCanaryGateError, match="durable Task 22 approval artifact"):
        authorize_mid_small_paper_canary(**kwargs)

    monkeypatch.setattr(orchestration_runner, "MID_SMALL_PRODUCTION_CANARY_ENABLED", True)
    authorization = authorize_mid_small_paper_canary(**kwargs)
    assert authorization.strategies == ("close_confirmed_breakout",)
    assert authorization.production_schedule_authorized is False
    assert authorization.paper_only is True
    assert authorization.no_live_execution is True

    with pytest.raises(PaperCanaryGateError, match="approved breakout"):
        authorize_mid_small_paper_canary(
            **{**kwargs, "strategies": ("trend_pullback_reclaim",)}
        )
    with pytest.raises(PaperCanaryGateError, match="exactly one existing publisher"):
        authorize_mid_small_paper_canary(**{**kwargs, "publisher_count": 2})


def test_paper_canary_execution_rejects_authorization_not_minted_by_preflight(monkeypatch):
    import orchestration_runner
    from orchestration_runner import (
        MID_SMALL_PAPER_RELEASE_CONFIG_VERSION,
        PaperCanaryAuthorization,
        PaperCanaryGateError,
        run_bounded_paper_canary,
    )

    forged = PaperCanaryAuthorization(
        snapshot_fingerprint="d" * 64,
        config_version=MID_SMALL_PAPER_RELEASE_CONFIG_VERSION,
        strategies=("close_confirmed_breakout",),
        rollback_command="restore_previous_publisher",
    )
    monkeypatch.setattr(orchestration_runner, "MID_SMALL_PRODUCTION_CANARY_ENABLED", True)
    with pytest.raises(PaperCanaryGateError, match="preflight-minted"):
        run_bounded_paper_canary(
            forged,
            publish=lambda **_kwargs: pytest.fail("publisher must not run"),
            read_invariants=lambda **_kwargs: pytest.fail("read-back must not run"),
            rollback=lambda **_kwargs: pytest.fail("rollback must not run"),
        )


def test_bounded_paper_canary_runs_once_reruns_idempotently_and_never_schedules(monkeypatch):
    import orchestration_runner

    from orchestration_runner import (
        MID_SMALL_PAPER_RELEASE_CONFIG_VERSION,
        run_bounded_paper_canary,
    )

    snapshot = "c" * 64
    monkeypatch.setattr(orchestration_runner, "MID_SMALL_PRODUCTION_CANARY_ENABLED", True)
    authorization = orchestration_runner.authorize_mid_small_paper_canary(
        shadow_report=_approved_shadow_release(snapshot),
        snapshot_fingerprint=snapshot,
        release_enabled=True,
        config_version=MID_SMALL_PAPER_RELEASE_CONFIG_VERSION,
        strategies=("close_confirmed_breakout",),
        publisher_count=1,
        rollback_command="restore_previous_publisher",
    )
    calls = []
    recommendation_ids = ("11111111-1111-4111-8111-111111111111",)

    def publication(authorization, *, created):
        result_material = json.dumps(
            {
                "recommendation_ids": recommendation_ids,
                "scope_fingerprint": authorization.scope_fingerprint,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return {
            "status": "paper_canary_complete",
            "recommendations_created": created,
            "recommendation_ids": recommendation_ids,
            "result_fingerprint": hashlib.sha256(result_material).hexdigest(),
            "scope_fingerprint": authorization.scope_fingerprint,
            "snapshot_fingerprint": authorization.snapshot_fingerprint,
            "config_version": authorization.config_version,
            "strategies": authorization.strategies,
            "research_only_published": 0,
            "paper_only": True,
            "no_live_execution": True,
            "broker_order_submitted": False,
            "broker_orders_created": 0,
            "external_deliveries": 0,
        }

    def publish(*, authorization, rerun: bool):
        calls.append(rerun)
        return publication(authorization, created=0 if rerun else 1)

    def read_invariants(*, authorization):
        return {
            "scope_fingerprint": authorization.scope_fingerprint,
            "snapshot_fingerprint": authorization.snapshot_fingerprint,
            "config_version": authorization.config_version,
            "strategies": authorization.strategies,
            "recommendation_ids": recommendation_ids,
            "recommendation_strategies": {
                recommendation_ids[0]: "liquid_rs_breakout_close_confirm_1r"
            },
            "positions_total": 20,
            "maximum_sector_positions": 5,
            "risk_fractions": ("0.05",) * 20,
            "aggregate_risk": "1.00",
            "instrument_provenance_or_fallback": True,
            "outcomes_linked": True,
            "research_only_published": 0,
            "paper_only": True,
            "no_live_execution": True,
            "broker_order_submitted": False,
            "broker_orders_created": 0,
        }

    def rollback(*, authorization, command, dry_run):
        assert command == authorization.rollback_command
        return {
            "command": command,
            "scope_fingerprint": authorization.scope_fingerprint,
            "snapshot_fingerprint": authorization.snapshot_fingerprint,
            "pivot_publisher_enabled": dry_run,
            "previous_publisher_restored": not dry_run,
            "previous_universe_restored": not dry_run,
            "rows_deleted": 0,
            "validated": True,
        }

    monkeypatch.setattr(orchestration_runner, "MID_SMALL_PRODUCTION_CANARY_ENABLED", True)
    result = run_bounded_paper_canary(
        authorization,
        publish=publish,
        read_invariants=read_invariants,
        rollback=rollback,
    )

    assert calls == [False, True]
    assert result.status == "paper_canary_complete"
    assert result.idempotent_rerun is True
    assert result.rollback_ready is True
    assert result.production_schedule_authorized is False
    assert result.broker_orders_created == 0


def test_paper_canary_safety_failure_rolls_back_without_deleting_audit_rows(monkeypatch):
    import orchestration_runner

    from orchestration_runner import (
        MID_SMALL_PAPER_RELEASE_CONFIG_VERSION,
        PaperCanaryGateError,
        run_bounded_paper_canary,
    )

    snapshot = "e" * 64
    monkeypatch.setattr(orchestration_runner, "MID_SMALL_PRODUCTION_CANARY_ENABLED", True)
    authorization = orchestration_runner.authorize_mid_small_paper_canary(
        shadow_report=_approved_shadow_release(snapshot),
        snapshot_fingerprint=snapshot,
        release_enabled=True,
        config_version=MID_SMALL_PAPER_RELEASE_CONFIG_VERSION,
        strategies=("close_confirmed_breakout",),
        publisher_count=1,
        rollback_command="restore_previous_publisher",
    )
    rollback_calls = []

    def rollback(*, authorization, command, dry_run):
        rollback_calls.append(dry_run)
        return {
            "command": command,
            "scope_fingerprint": authorization.scope_fingerprint,
            "snapshot_fingerprint": authorization.snapshot_fingerprint,
            "pivot_publisher_enabled": dry_run,
            "previous_publisher_restored": not dry_run,
            "previous_universe_restored": not dry_run,
            "rows_deleted": 0,
            "validated": True,
        }

    def unsafe_publish(*, authorization, rerun):
        del rerun
        recommendation_ids = ("22222222-2222-4222-8222-222222222222",)
        material = json.dumps(
            {
                "recommendation_ids": recommendation_ids,
                "scope_fingerprint": authorization.scope_fingerprint,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return {
            "status": "paper_canary_complete",
            "recommendations_created": 1,
            "recommendation_ids": recommendation_ids,
            "result_fingerprint": hashlib.sha256(material).hexdigest(),
            "scope_fingerprint": authorization.scope_fingerprint,
            "snapshot_fingerprint": authorization.snapshot_fingerprint,
            "config_version": authorization.config_version,
            "strategies": authorization.strategies,
            "research_only_published": 0,
            "paper_only": True,
            "no_live_execution": True,
            "broker_order_submitted": False,
            "broker_orders_created": 1,
            "external_deliveries": 0,
        }

    monkeypatch.setattr(orchestration_runner, "MID_SMALL_PRODUCTION_CANARY_ENABLED", True)
    with pytest.raises(PaperCanaryGateError, match="broker_orders_created"):
        run_bounded_paper_canary(
            authorization,
            publish=unsafe_publish,
            read_invariants=lambda **_kwargs: {},
            rollback=rollback,
        )
    assert rollback_calls == [True, False]


def test_paper_canary_rollback_requires_previous_universe_restoration():
    from orchestration_runner import (
        MID_SMALL_PAPER_RELEASE_CONFIG_VERSION,
        PaperCanaryAuthorization,
        PaperCanaryGateError,
        _execute_safe_rollback,
    )

    authorization = PaperCanaryAuthorization(
        snapshot_fingerprint="f" * 64,
        config_version=MID_SMALL_PAPER_RELEASE_CONFIG_VERSION,
        strategies=("close_confirmed_breakout",),
        rollback_command="restore_previous_publisher",
    )

    def incomplete_rollback(*, authorization, command, dry_run):
        return {
            "command": command,
            "scope_fingerprint": authorization.scope_fingerprint,
            "snapshot_fingerprint": authorization.snapshot_fingerprint,
            "pivot_publisher_enabled": dry_run,
            "previous_publisher_restored": not dry_run,
            "rows_deleted": 0,
            "validated": True,
        }

    with pytest.raises(PaperCanaryGateError, match="rollback evidence"):
        _execute_safe_rollback(incomplete_rollback, authorization, dry_run=False)
