from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
import uuid

import pytest

from eod_readiness import EODReadiness, SourceMode
from test_db import test_connection


SNAPSHOT_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _readiness(*, publishable: bool = True) -> EODReadiness:
    reasons = () if publishable else ("benchmark_incomplete",)
    return EODReadiness(
        expected_session=date(2099, 5, 1),
        latest_complete_session=date(2099, 5, 1) if publishable else None,
        coverage_numerator=4 if publishable else 3,
        coverage_denominator=4,
        missing_symbols=() if publishable else ("SPY",),
        source_mode=SourceMode.FREE_T_PLUS_1,
        publishable=publishable,
        universe_snapshot_id=str(SNAPSHOT_ID),
        universe_policy_version="mid_small_multi_strategy_pivot_v1",
        universe_source_fingerprint="a" * 64,
        benchmark_coverage_numerator=3 if publishable else 2,
        benchmark_coverage_denominator=3,
        member_coverage_numerator=1,
        member_coverage_denominator=1,
        incomplete_reasons=reasons,
    )


def _candidate(ticker: str = "ZZPIVOT", *, sector: str = "Industrials"):
    from portfolio_allocator import PortfolioCandidate

    return PortfolioCandidate(
        candidate_id=uuid.uuid5(uuid.NAMESPACE_DNS, ticker),
        universe_snapshot_id=SNAPSHOT_ID,
        ticker=ticker,
        strategy_id="liquid_rs_breakout_close_confirm_1r",
        strategy_version="approved-2026-08-03",
        sector=sector,
        score=Decimal("2.5"),
        entry=Decimal("20"),
        stop=Decimal("19"),
        target=Decimal("22"),
    )


def test_incomplete_pipeline_fails_before_any_read_or_write():
    from daily_multi_strategy import run_underlying_pivot_slice

    class NoDatabaseAccess:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("incomplete pipeline touched the database")

    result = run_underlying_pivot_slice(
        NoDatabaseAccess(),
        signal_dt=date(2099, 5, 1),
        readiness=_readiness(publishable=False),
        candidates=[_candidate()],
        dry_run=False,
    )

    assert result["status"] == "pipeline_incomplete"
    assert result["recommendations_created"] == 0
    assert result["broker_orders_created"] == 0
    assert result["incomplete_reasons"] == ["benchmark_incomplete"]


def test_ready_approved_breakout_writes_stock_fallback_idempotently_in_wolfy_test():
    from daily_multi_strategy import run_underlying_pivot_slice

    ticker = f"ZZ{uuid.uuid4().hex[:8].upper()}"
    candidate = _candidate(ticker)
    with test_connection() as conn:
        try:
            first = run_underlying_pivot_slice(
                conn,
                signal_dt=date(2099, 5, 1),
                readiness=_readiness(),
                candidates=[candidate],
                dry_run=False,
            )
            second = run_underlying_pivot_slice(
                conn,
                signal_dt=date(2099, 5, 1),
                readiness=_readiness(),
                candidates=[candidate],
                dry_run=False,
            )
            row = conn.execute(
                "SELECT recommendation_type,status,notes FROM recommendations WHERE ticker=%s",
                (ticker,),
            ).fetchone()
        finally:
            conn.execute("DELETE FROM recommendations WHERE ticker=%s", (ticker,))

    assert first["status"] == "shadow_recommendations"
    assert first["recommendations_created"] == 1
    assert second["recommendations_created"] == 0
    assert second["status"] == "no_new_recommendations"
    assert row[0:2] == ("underlying_stock_fallback", "paper_candidate")
    assert row[2]["instrument_expression"] == "underlying_stock_fallback"
    assert row[2]["instrument_reason"] == "option_engine_not_release_ready"
    assert row[2]["risk_fraction"] == "0.05"
    assert row[2]["paper_only"] is True
    assert row[2]["no_live_execution"] is True
    assert row[2]["broker_order_submitted"] is False
    assert first["broker_orders_created"] == 0


def test_zero_candidates_and_research_only_candidates_do_not_publish():
    from daily_multi_strategy import run_underlying_pivot_slice

    class ReadOnlyEmptyConnection:
        def execute(self, statement, params=None):
            del statement, params
            raise AssertionError("empty or research-only candidate set touched database")

    empty = run_underlying_pivot_slice(
        ReadOnlyEmptyConnection(),
        signal_dt=date(2099, 5, 1),
        readiness=_readiness(),
        candidates=[],
        dry_run=False,
    )
    research = _candidate()
    object.__setattr__(research, "strategy_id", "mid_small_trend_pullback_reclaim_v1")
    blocked = run_underlying_pivot_slice(
        ReadOnlyEmptyConnection(),
        signal_dt=date(2099, 5, 1),
        readiness=_readiness(),
        candidates=[research],
        dry_run=False,
    )

    assert empty["status"] == "no_candidates"
    assert blocked["status"] == "no_candidates"
    assert blocked["research_only_blocked"] == 1


def _shadow_request(**overrides):
    from daily_multi_strategy import ShadowPipelineRequest

    values = {
        "run_id": uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        "signal_dt": date(2099, 5, 1),
        "decision_at": datetime(2099, 5, 2, 1, tzinfo=timezone.utc),
        "universe_snapshot_id": SNAPSHOT_ID,
        "universe_fingerprint": "a" * 64,
        "account_equity": Decimal("10000"),
        "strategies": (
            "close_confirmed_breakout",
            "trend_pullback_reclaim",
            "volatility_contraction_breakout",
        ),
        "tickers": (),
        "dry_run": False,
        "shadow": True,
    }
    values.update(overrides)
    return ShadowPipelineRequest(**values)


def _shadow_hooks(events, *, candidates=None, readiness=None, chain_value=None, crash_once=None):
    from daily_multi_strategy import ShadowPipelineHooks

    candidate_rows = [_candidate()] if candidates is None else candidates
    ready = _readiness() if readiness is None else readiness

    def stage(name, value):
        def invoke(_context, *args):
            del args
            events.append(name)
            if crash_once == name and events.count(name) == 1:
                raise RuntimeError(f"{name} crash")
            return value

        return invoke

    def chains(_context, candidate):
        events.append(f"chain:{candidate.ticker}")
        if isinstance(chain_value, Exception):
            raise chain_value
        return chain_value

    def forbidden_writer(*_args, **_kwargs):
        raise AssertionError("shadow mode invoked recommendation writer")

    return ShadowPipelineHooks(
        readiness=stage("readiness", ready),
        universe=stage(
            "universe",
            {"snapshot_id": str(SNAPSHOT_ID), "fingerprint": "a" * 64},
        ),
        features=stage("features", {"feature_rows": 1}),
        evaluations=stage("evaluations", tuple(candidate_rows)),
        existing_positions=stage("existing_positions", ()),
        acquire_chain=chains,
        recommendation_writer=forbidden_writer,
        outcomes=stage("outcomes", {"underlying": 0, "option": 0}),
        summary=stage("summary", "shadow summary"),
    )


def test_full_shadow_orchestrator_runs_all_stages_and_falls_back_on_chain_outage():
    from daily_multi_strategy import ShadowStageLedger, run_shadow_pipeline
    from option_chain_provider import OptionChainProviderUnavailable

    events = []
    ledger = ShadowStageLedger()
    result = run_shadow_pipeline(
        _shadow_request(),
        _shadow_hooks(events, chain_value=OptionChainProviderUnavailable("offline")),
        ledger=ledger,
    )

    assert result.status == "shadow_complete"
    assert result.stage_names == (
        "readiness",
        "universe",
        "features_context",
        "setup_evaluations",
        "candidate_persistence",
        "allocation",
        "finalist_chains",
        "instrument_decisions",
        "serialized_write",
        "outcomes",
        "summary",
    )
    assert result.instrument_decisions[0].expression == "underlying_stock_fallback"
    assert result.instrument_decisions[0].fallback_reasons == ("option_chain_unavailable",)
    assert result.recommendations_created == 0
    assert result.broker_orders_created == 0
    assert result.external_deliveries == 0
    assert "serialized_write" not in events
    assert ledger.read_back(result.run_id, result.input_fingerprint) == result.stage_names

    completed_events = tuple(events)
    rerun = run_shadow_pipeline(
        _shadow_request(),
        _shadow_hooks(events, chain_value=OptionChainProviderUnavailable("offline")),
        ledger=ledger,
    )
    assert rerun == result
    assert tuple(events) == completed_events


def test_shadow_orchestrator_retries_after_stage_crash_and_rejects_conflicting_fingerprint():
    from daily_multi_strategy import ShadowPipelineConflict, ShadowStageLedger, run_shadow_pipeline

    events = []
    ledger = ShadowStageLedger()
    hooks = _shadow_hooks(events, crash_once="features")
    request = _shadow_request()
    with pytest.raises(RuntimeError, match="features crash"):
        run_shadow_pipeline(request, hooks, ledger=ledger)

    result = run_shadow_pipeline(request, hooks, ledger=ledger)
    assert result.status == "shadow_complete"
    assert events.count("readiness") == 1
    assert events.count("universe") == 1
    assert events.count("features") == 2

    with pytest.raises(ShadowPipelineConflict, match="fingerprint"):
        run_shadow_pipeline(
            replace(request, account_equity=Decimal("11000")), hooks, ledger=ledger
        )


@pytest.mark.parametrize("mode", ["missing_readiness", "no_candidates", "allocation_blocked"])
def test_shadow_orchestrator_handles_incomplete_empty_and_capacity_states(mode):
    from daily_multi_strategy import ShadowStageLedger, run_shadow_pipeline
    from portfolio_allocator import ExistingPosition

    events = []
    readiness = _readiness(publishable=False) if mode == "missing_readiness" else _readiness()
    candidates = [] if mode == "no_candidates" else [_candidate()]
    hooks = _shadow_hooks(events, candidates=candidates, readiness=readiness)
    if mode == "allocation_blocked":
        hooks = replace(
            hooks,
            existing_positions=lambda _context: tuple(
                ExistingPosition(f"ZZ{i:02d}", f"Sector{i}") for i in range(20)
            ),
        )
    result = run_shadow_pipeline(_shadow_request(), hooks, ledger=ShadowStageLedger())

    expected = {
        "missing_readiness": "pipeline_incomplete",
        "no_candidates": "no_candidates",
        "allocation_blocked": "allocation_blocked",
    }
    assert result.status == expected[mode]
    assert result.recommendations_created == 0
    assert result.broker_orders_created == 0


def test_shadow_orchestrator_blocks_release_and_bounds_strategy_and_ticker_replay():
    from daily_multi_strategy import ShadowPipelineValidationError

    with pytest.raises(ShadowPipelineValidationError, match="shadow mode"):
        replace(_shadow_request(), shadow=False)
    with pytest.raises(ShadowPipelineValidationError, match="at most 20"):
        replace(_shadow_request(), tickers=tuple(f"ZZ{i:02d}" for i in range(21)))
    with pytest.raises(ShadowPipelineValidationError, match="strategy"):
        replace(_shadow_request(), strategies=("industry_rotation",))
