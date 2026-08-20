from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import json

import pytest


def _versioned_approved_gate(gate: dict) -> dict:
    return {
        **gate,
        "validation_mode": "underlying_setup_outcome_revalidation",
        "gate_definition_version": 1,
    }


def _cleanup(conn, ticker: str, strategy_names: list[str] | None = None) -> None:
    strategy_names = strategy_names or []
    conn.execute("DELETE FROM eod_monitoring_events WHERE ticker=%s", (ticker,))
    conn.execute("DELETE FROM setups WHERE ticker=%s", (ticker,))
    conn.execute("DELETE FROM positions WHERE ticker=%s", (ticker,))
    conn.execute("DELETE FROM earnings_calendar WHERE ticker=%s", (ticker,))
    conn.execute("DELETE FROM prices WHERE ticker=%s", (ticker,))
    if strategy_names:
        conn.execute("DELETE FROM research_log WHERE hypothesis LIKE 'monthly revalidation:%'")
        conn.execute("DELETE FROM backtests WHERE strategy_id IN (SELECT id FROM strategies WHERE name = ANY(%s))", (strategy_names,))
        conn.execute("DELETE FROM strategies WHERE name = ANY(%s)", (strategy_names,))


def test_preopen_monitoring_flags_invalidation_and_event_landmines_without_promoting():
    import psycopg
    from eod_monitoring import ensure_monitoring_schema, run_preopen_monitoring

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    ticker = "ZZMON"
    today = date(2026, 6, 3)
    with psycopg.connect(dsn) as conn:
        ensure_monitoring_schema(conn)
        _cleanup(conn, ticker)
        conn.execute(
            "INSERT INTO prices(ticker, dt, close) VALUES (%s,%s,%s)",
            (ticker, today - timedelta(days=1), Decimal("9.50")),
        )
        conn.execute(
            "INSERT INTO earnings_calendar(ticker, event_dt, session, confirmed) VALUES (%s,%s,'bmo',true)",
            (ticker, today),
        )
        setup_id = conn.execute(
            """
            INSERT INTO setups(created_dt, for_session, ticker, direction, invalidation, thesis, status)
            VALUES (%s,%s,%s,'long',%s,'unit monitor setup','pending_review') RETURNING id
            """,
            (today - timedelta(days=1), today, ticker, Decimal("10.00")),
        ).fetchone()[0]
        position_id = conn.execute(
            """
            INSERT INTO positions(ticker, opened, risk_amount, invalidation, status)
            VALUES (%s,%s,%s,%s,'open') RETURNING id
            """,
            (ticker, today - timedelta(days=2), Decimal("50"), Decimal("10.00")),
        ).fetchone()[0]

        result = run_preopen_monitoring(conn, as_of=today)
        setup_status = conn.execute("SELECT status FROM setups WHERE id=%s", (setup_id,)).fetchone()[0]
        position_status = conn.execute("SELECT status FROM positions WHERE id=%s", (position_id,)).fetchone()[0]
        events = conn.execute(
            "SELECT object_type, object_id, action, reason FROM eod_monitoring_events WHERE ticker=%s ORDER BY id",
            (ticker,),
        ).fetchall()
        _cleanup(conn, ticker)

    assert result["setups_flagged"] == 1
    assert result["positions_flagged"] == 1
    assert setup_status == "rejected"
    assert position_status == "flagged"
    assert {(row[0], row[1], row[2]) for row in events} == {("setup", setup_id, "rejected"), ("position", position_id, "flagged")}
    assert all("invalidation" in row[3] and "earnings" in row[3] for row in events)


def test_monthly_revalidation_demotes_stale_or_failed_approved_strategies_only():
    import psycopg
    from eod_monitoring import ensure_monitoring_schema, run_monthly_strategy_revalidation

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    as_of = date(2026, 6, 30)
    stale = "unit_stale_approved"
    fresh = "unit_fresh_approved"
    failed = "unit_failed_approved"
    with psycopg.connect(dsn) as conn:
        ensure_monitoring_schema(conn)
        _cleanup(conn, "ZZREV", [stale, fresh, failed])
        conn.execute(
            "INSERT INTO strategies(name, setup_type, status, latest_oos_verdict, last_validated, notes) VALUES (%s,'unit','approved',true,%s,'stale')",
            (stale, as_of - timedelta(days=45)),
        )
        conn.execute(
            "INSERT INTO strategies(name, setup_type, status, latest_oos_verdict, last_validated, notes) VALUES (%s,'unit','approved',true,%s,'fresh')",
            (fresh, as_of - timedelta(days=10)),
        )
        conn.execute(
            "INSERT INTO strategies(name, setup_type, status, latest_oos_verdict, last_validated, notes) VALUES (%s,'unit','approved',false,%s,'failed')",
            (failed, as_of - timedelta(days=5)),
        )

        result = run_monthly_strategy_revalidation(conn, as_of=as_of, stale_after_days=31)
        statuses = dict(conn.execute("SELECT name, status FROM strategies WHERE name = ANY(%s)", ([stale, fresh, failed],)).fetchall())
        research_rows = conn.execute(
            "SELECT hypothesis, outcome, promoted FROM research_log WHERE hypothesis = ANY(%s) ORDER BY id",
            ([f"monthly revalidation:{stale}", f"monthly revalidation:{failed}"],),
        ).fetchall()
        _cleanup(conn, "ZZREV", [stale, fresh, failed])

    assert result["strategies_demoted"] >= 2
    assert statuses == {stale: "candidate", fresh: "approved", failed: "candidate"}
    assert len(research_rows) == 2
    assert all(row[1] == "demoted_to_candidate" and row[2] is False for row in research_rows)


def test_setup_outcome_revalidation_reactivates_only_previously_authorized_candidate():
    import psycopg
    from eod_monitoring import run_setup_outcome_strategy_revalidation

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    strategy_name = "unit_setup_outcome_reactivation"
    tickers = ["ZZRV1", "ZZRV2", "ZZRV3"]
    signal_dates = [date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12)]
    validation_run_date = date(2026, 8, 19)
    metadata = {
        "approval_scope": "paper_only_no_live_execution",
        "paper_recommendation_approval": True,
        "future_same_gate_auto_activation_allowed": True,
        "latest_setup_outcome_gate": {
            "passed": True,
            "thresholds": {
                "min_sample": 3,
                "min_oos_sample": 1,
                "min_hit_rate": "0.50",
                "min_oos_hit_rate": "0.50",
                "max_stop_rate": "0.50",
                "min_median_mfe_r": "1.0",
                "oos_fraction": "0.34",
            },
        },
    }
    metadata["approved_setup_outcome_gate"] = _versioned_approved_gate(metadata["latest_setup_outcome_gate"])
    with psycopg.connect(dsn) as conn:
        conn.execute("DELETE FROM research_log WHERE hypothesis=%s", (f"setup outcome revalidation:{strategy_name}",))
        conn.execute("DELETE FROM backtests WHERE strategy_id IN (SELECT id FROM strategies WHERE name=%s)", (strategy_name,))
        conn.execute("DELETE FROM signals WHERE ticker = ANY(%s)", (tickers,))
        conn.execute("DELETE FROM prices WHERE ticker = ANY(%s)", (tickers,))
        conn.execute("DELETE FROM strategies WHERE name=%s", (strategy_name,))
        strategy_id = conn.execute(
            """
            INSERT INTO strategies(name, setup_type, status, latest_oos_verdict, last_validated, metadata)
            VALUES (%s,'unit','candidate',true,%s,%s::jsonb)
            RETURNING id
            """,
            (strategy_name, date(2026, 7, 1), json.dumps(metadata)),
        ).fetchone()[0]
        for ticker, signal_dt in zip(tickers, signal_dates):
            conn.execute(
                "INSERT INTO signals(dt,ticker,direction,raw,strategy_id) VALUES (%s,%s,'long',%s::jsonb,%s)",
                (
                    signal_dt,
                    ticker,
                    json.dumps({
                        "close": "100",
                        "invalidation": "99",
                        "target_r": "1.0",
                        "max_hold_days": 2,
                        "stop_rule": "close_below_breakout_level",
                    }),
                    strategy_id,
                ),
            )
            conn.execute(
                "INSERT INTO prices(ticker,dt,open,high,low,close,volume) VALUES (%s,%s,100,101.25,99.50,101.10,1000000)",
                (ticker, signal_dt + timedelta(days=1)),
            )

        result = run_setup_outcome_strategy_revalidation(
            conn,
            strategy_name=strategy_name,
            as_of=date(2026, 8, 18),
            validation_run_date=validation_run_date,
        )
        state = conn.execute(
            "SELECT status,last_validated,latest_oos_verdict,metadata FROM strategies WHERE id=%s",
            (strategy_id,),
        ).fetchone()
        backtest = conn.execute(
            "SELECT survives_oos,report FROM backtests WHERE strategy_id=%s ORDER BY id DESC LIMIT 1",
            (strategy_id,),
        ).fetchone()

        conn.execute("DELETE FROM research_log WHERE hypothesis=%s", (f"setup outcome revalidation:{strategy_name}",))
        conn.execute("DELETE FROM backtests WHERE strategy_id=%s", (strategy_id,))
        conn.execute("DELETE FROM signals WHERE ticker = ANY(%s)", (tickers,))
        conn.execute("DELETE FROM prices WHERE ticker = ANY(%s)", (tickers,))
        conn.execute("DELETE FROM strategies WHERE id=%s", (strategy_id,))

    assert result["passed"] is True
    assert result["reactivated"] is True
    assert state[0:3] == ("approved", validation_run_date, True)
    assert state[3]["latest_setup_outcome_gate"]["passed"] is True
    assert state[3]["latest_setup_outcome_gate"]["validation_mode"] == "underlying_setup_outcome_revalidation"
    assert state[3]["latest_setup_outcome_gate"]["gate_definition_version"] == 1
    assert state[3]["validated_through"] == "2026-08-13"
    assert backtest[0] is True
    assert backtest[1]["validation_mode"] == "underlying_setup_outcome_revalidation"


def test_monthly_revalidation_refreshes_authorized_setup_strategy_before_demotion():
    import psycopg
    from eod_monitoring import run_monthly_strategy_revalidation

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    strategy_name = "unit_monthly_setup_refresh"
    ticker = "ZZRVM"
    as_of = date(2026, 8, 19)
    metadata = {
        "approval_scope": "paper_only_no_live_execution",
        "paper_recommendation_approval": True,
        "future_same_gate_auto_activation_allowed": True,
        "latest_setup_outcome_gate": {
            "passed": True,
            "thresholds": {
                "min_sample": 1,
                "min_oos_sample": 1,
                "min_hit_rate": "0.50",
                "min_oos_hit_rate": "0.50",
                "max_stop_rate": "0.50",
                "min_median_mfe_r": "1.0",
                "oos_fraction": "1.0",
            },
        },
    }
    metadata["approved_setup_outcome_gate"] = _versioned_approved_gate(metadata["latest_setup_outcome_gate"])
    with psycopg.connect(dsn) as conn:
        conn.execute("DELETE FROM research_log WHERE hypothesis LIKE %s", (f"%{strategy_name}",))
        conn.execute("DELETE FROM backtests WHERE strategy_id IN (SELECT id FROM strategies WHERE name=%s)", (strategy_name,))
        conn.execute("DELETE FROM signals WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM prices WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM strategies WHERE name=%s", (strategy_name,))
        strategy_id = conn.execute(
            """
            INSERT INTO strategies(name,setup_type,status,latest_oos_verdict,last_validated,metadata)
            VALUES (%s,'unit','candidate',true,%s,%s::jsonb) RETURNING id
            """,
            (strategy_name, as_of - timedelta(days=60), json.dumps(metadata)),
        ).fetchone()[0]
        signal_dt = as_of - timedelta(days=3)
        conn.execute(
            "INSERT INTO signals(dt,ticker,direction,raw,strategy_id) VALUES (%s,%s,'long',%s::jsonb,%s)",
            (signal_dt, ticker, json.dumps({"close": "100", "invalidation": "99", "target_r": "1", "max_hold_days": 1}), strategy_id),
        )
        conn.execute(
            "INSERT INTO prices(ticker,dt,open,high,low,close,volume) VALUES (%s,%s,100,101.20,99.50,101.10,1000000)",
            (ticker, signal_dt + timedelta(days=1)),
        )

        result = run_monthly_strategy_revalidation(
            conn,
            as_of=as_of,
            stale_after_days=31,
            strategy_names=[strategy_name],
        )
        state = conn.execute(
            "SELECT status,last_validated,metadata FROM strategies WHERE id=%s",
            (strategy_id,),
        ).fetchone()

        conn.execute("DELETE FROM research_log WHERE hypothesis LIKE %s", (f"%{strategy_name}",))
        conn.execute("DELETE FROM backtests WHERE strategy_id=%s", (strategy_id,))
        conn.execute("DELETE FROM signals WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM prices WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM strategies WHERE id=%s", (strategy_id,))

    assert result["strategies_revalidated"] == 1
    assert result["strategies_reactivated"] == 1
    assert state[0:2] == ("approved", as_of)
    assert state[2]["validated_through"] == "2026-08-17"


def test_monthly_revalidation_routes_fresh_approved_invalid_gate_through_fail_closed_demotion():
    import psycopg
    from eod_monitoring import run_monthly_strategy_revalidation

    strategy_name = "unit_fresh_invalid_approved_gate"
    as_of = date(2026, 8, 19)
    metadata = {
        "approval_scope": "paper_only_no_live_execution",
        "paper_recommendation_approval": True,
        "future_same_gate_auto_activation_allowed": True,
        "approved_setup_outcome_gate": {
            "passed": True,
            "validation_mode": "underlying_setup_outcome_revalidation",
            "gate_definition_version": 2,
            "thresholds": {
                "min_sample": 100,
                "min_oos_sample": 25,
                "min_hit_rate": "0.55",
                "min_oos_hit_rate": "0.50",
                "max_stop_rate": "0.45",
                "min_median_mfe_r": "1.0",
                "oos_fraction": "0.25",
            },
        },
    }
    with psycopg.connect("dbname=wolfy user=root host=/var/run/postgresql") as conn:
        conn.execute("DELETE FROM research_log WHERE hypothesis LIKE %s", (f"%{strategy_name}",))
        conn.execute("DELETE FROM backtests WHERE strategy_id IN (SELECT id FROM strategies WHERE name=%s)", (strategy_name,))
        conn.execute("DELETE FROM strategies WHERE name=%s", (strategy_name,))
        strategy_id = conn.execute(
            """
            INSERT INTO strategies(name,setup_type,status,latest_oos_verdict,last_validated,metadata)
            VALUES (%s,'unit','approved',true,%s,%s::jsonb) RETURNING id
            """,
            (strategy_name, as_of, json.dumps(metadata)),
        ).fetchone()[0]

        result = run_monthly_strategy_revalidation(
            conn,
            as_of=as_of,
            stale_after_days=31,
            strategy_names=[strategy_name],
        )
        state = conn.execute(
            "SELECT status,latest_oos_verdict,metadata FROM strategies WHERE id=%s",
            (strategy_id,),
        ).fetchone()

        conn.execute("DELETE FROM research_log WHERE hypothesis LIKE %s", (f"%{strategy_name}",))
        conn.execute("DELETE FROM backtests WHERE strategy_id=%s", (strategy_id,))
        conn.execute("DELETE FROM strategies WHERE id=%s", (strategy_id,))

    assert result["strategies_revalidated"] == 1
    assert result["strategies_demoted"] == 1
    assert state[0:2] == ("candidate", False)
    assert state[2]["latest_setup_outcome_gate"]["passed"] is False
    assert state[2]["latest_setup_outcome_gate"]["approved_gate_definition_valid"] is False


def test_failed_revalidation_preserves_approval_gate_for_later_same_gate_reactivation():
    import psycopg
    from eod_monitoring import run_monthly_strategy_revalidation

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    strategy_name = "unit_revalidation_recovery"
    tickers = ["ZZRVF", "ZZRVP1", "ZZRVP2"]
    metadata = {
        "approval_scope": "paper_only_no_live_execution",
        "paper_recommendation_approval": True,
        "future_same_gate_auto_activation_allowed": True,
        "latest_setup_outcome_gate": {
            "passed": True,
            "thresholds": {
                "min_sample": 1,
                "min_oos_sample": 1,
                "min_hit_rate": "0.50",
                "min_oos_hit_rate": "0.50",
                "max_stop_rate": "0.40",
                "min_median_mfe_r": "1.0",
                "oos_fraction": "1.0",
            },
        },
    }
    metadata["approved_setup_outcome_gate"] = _versioned_approved_gate(metadata["latest_setup_outcome_gate"])
    first_as_of = date(2026, 8, 10)
    second_as_of = date(2026, 8, 15)
    with psycopg.connect(dsn) as conn:
        conn.execute("DELETE FROM research_log WHERE hypothesis LIKE %s", (f"%{strategy_name}",))
        conn.execute("DELETE FROM backtests WHERE strategy_id IN (SELECT id FROM strategies WHERE name=%s)", (strategy_name,))
        conn.execute("DELETE FROM signals WHERE ticker = ANY(%s)", (tickers,))
        conn.execute("DELETE FROM prices WHERE ticker = ANY(%s)", (tickers,))
        conn.execute("DELETE FROM strategies WHERE name=%s", (strategy_name,))
        strategy_id = conn.execute(
            """
            INSERT INTO strategies(name,setup_type,status,latest_oos_verdict,last_validated,metadata)
            VALUES (%s,'unit','approved',true,%s,%s::jsonb) RETURNING id
            """,
            (strategy_name, date(2026, 6, 1), json.dumps(metadata)),
        ).fetchone()[0]
        failed_signal_dt = date(2026, 8, 7)
        conn.execute(
            "INSERT INTO signals(dt,ticker,direction,raw,strategy_id) VALUES (%s,%s,'long',%s::jsonb,%s)",
            (failed_signal_dt, tickers[0], json.dumps({"close": "100", "invalidation": "99", "target_r": "1", "max_hold_days": 1}), strategy_id),
        )
        conn.execute(
            "INSERT INTO prices(ticker,dt,open,high,low,close,volume) VALUES (%s,%s,100,100.2,98.5,98.8,1000000)",
            (tickers[0], failed_signal_dt + timedelta(days=1)),
        )

        failed = run_monthly_strategy_revalidation(
            conn,
            as_of=first_as_of,
            stale_after_days=31,
            strategy_names=[strategy_name],
        )
        failed_state = conn.execute("SELECT status,metadata FROM strategies WHERE id=%s", (strategy_id,)).fetchone()

        for ticker, signal_dt in zip(tickers[1:], [date(2026, 8, 11), date(2026, 8, 12)]):
            conn.execute(
                "INSERT INTO signals(dt,ticker,direction,raw,strategy_id) VALUES (%s,%s,'long',%s::jsonb,%s)",
                (signal_dt, ticker, json.dumps({"close": "100", "invalidation": "99", "target_r": "1", "max_hold_days": 1}), strategy_id),
            )
            conn.execute(
                "INSERT INTO prices(ticker,dt,open,high,low,close,volume) VALUES (%s,%s,100,101.2,99.5,101.1,1000000)",
                (ticker, signal_dt + timedelta(days=1)),
            )

        recovered = run_monthly_strategy_revalidation(
            conn,
            as_of=second_as_of,
            stale_after_days=31,
            strategy_names=[strategy_name],
        )
        recovered_state = conn.execute("SELECT status,metadata FROM strategies WHERE id=%s", (strategy_id,)).fetchone()

        conn.execute("DELETE FROM research_log WHERE hypothesis LIKE %s", (f"%{strategy_name}",))
        conn.execute("DELETE FROM backtests WHERE strategy_id=%s", (strategy_id,))
        conn.execute("DELETE FROM signals WHERE ticker = ANY(%s)", (tickers,))
        conn.execute("DELETE FROM prices WHERE ticker = ANY(%s)", (tickers,))
        conn.execute("DELETE FROM strategies WHERE id=%s", (strategy_id,))

    assert failed["strategies_demoted"] == 1
    assert failed_state[0] == "candidate"
    assert failed_state[1]["latest_setup_outcome_gate"]["passed"] is False
    assert failed_state[1]["approved_setup_outcome_gate"]["passed"] is True
    assert recovered["strategies_reactivated"] == 1
    assert recovered_state[0] == "approved"
    assert recovered_state[1]["latest_setup_outcome_gate"]["passed"] is True
    assert recovered_state[1]["approved_setup_outcome_gate"]["passed"] is True


def test_setup_outcome_revalidation_rejects_invalid_target_and_holding_metadata():
    import psycopg
    from eod_monitoring import run_setup_outcome_strategy_revalidation

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    strategy_name = "unit_invalid_revalidation_metadata"
    ticker = "ZZRVINV"
    signal_dt = date(2026, 8, 10)
    metadata = {
        "approval_scope": "paper_only_no_live_execution",
        "paper_recommendation_approval": True,
        "future_same_gate_auto_activation_allowed": True,
        "latest_setup_outcome_gate": {
            "passed": True,
            "thresholds": {"min_sample": 1, "min_oos_sample": 1},
        },
    }
    with psycopg.connect(dsn) as conn:
        conn.execute("DELETE FROM research_log WHERE hypothesis LIKE %s", (f"%{strategy_name}",))
        conn.execute("DELETE FROM backtests WHERE strategy_id IN (SELECT id FROM strategies WHERE name=%s)", (strategy_name,))
        conn.execute("DELETE FROM signals WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM prices WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM strategies WHERE name=%s", (strategy_name,))
        strategy_id = conn.execute(
            "INSERT INTO strategies(name,setup_type,status,metadata) VALUES (%s,'unit','candidate',%s::jsonb) RETURNING id",
            (strategy_name, json.dumps(metadata)),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO signals(dt,ticker,direction,raw,strategy_id) VALUES (%s,%s,'long',%s::jsonb,%s)",
            (signal_dt, ticker, json.dumps({"close": "100", "invalidation": "99", "target_r": "-1", "max_hold_days": 1}), strategy_id),
        )
        conn.execute(
            "INSERT INTO signals(dt,ticker,direction,raw,strategy_id) VALUES (%s,%s,'long',%s::jsonb,%s)",
            (signal_dt + timedelta(days=1), ticker, json.dumps(5), strategy_id),
        )
        conn.execute(
            "INSERT INTO prices(ticker,dt,open,high,low,close,volume) VALUES (%s,%s,100,100.2,99.5,100.1,1000000)",
            (ticker, signal_dt + timedelta(days=1)),
        )

        result = run_setup_outcome_strategy_revalidation(
            conn,
            strategy_name=strategy_name,
            as_of=signal_dt + timedelta(days=2),
        )

        conn.execute("DELETE FROM research_log WHERE hypothesis LIKE %s", (f"%{strategy_name}",))
        conn.execute("DELETE FROM backtests WHERE strategy_id=%s", (strategy_id,))
        conn.execute("DELETE FROM signals WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM prices WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM strategies WHERE id=%s", (strategy_id,))

    assert result["passed"] is False
    assert result["reactivated"] is False
    assert result["gate"]["observed"]["sample"] == 0


def test_incomplete_approved_gate_cannot_authorize_candidate_reactivation():
    import psycopg
    from eod_monitoring import run_setup_outcome_strategy_revalidation

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    strategy_name = "unit_incomplete_approval_gate"
    ticker = "ZZRVGAP"
    signal_dt = date(2026, 8, 10)
    incomplete_thresholds = {
        "min_sample": 1,
        "min_oos_sample": 1,
        "min_hit_rate": "0.50",
        "min_oos_hit_rate": "0.50",
        "max_stop_rate": "0.50",
        "min_median_mfe_r": "1.0",
        # oos_fraction intentionally absent: defaults would otherwise permit a pass.
    }
    metadata = {
        "approval_scope": "paper_only_no_live_execution",
        "paper_recommendation_approval": True,
        "future_same_gate_auto_activation_allowed": True,
        "approved_setup_outcome_gate": {"passed": True, "thresholds": incomplete_thresholds},
        "latest_setup_outcome_gate": {"passed": True, "thresholds": incomplete_thresholds},
    }
    with psycopg.connect(dsn) as conn:
        conn.execute("DELETE FROM research_log WHERE hypothesis LIKE %s", (f"%{strategy_name}",))
        conn.execute("DELETE FROM backtests WHERE strategy_id IN (SELECT id FROM strategies WHERE name=%s)", (strategy_name,))
        conn.execute("DELETE FROM signals WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM prices WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM strategies WHERE name=%s", (strategy_name,))
        strategy_id = conn.execute(
            "INSERT INTO strategies(name,setup_type,status,metadata) VALUES (%s,'unit','candidate',%s::jsonb) RETURNING id",
            (strategy_name, json.dumps(metadata)),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO signals(dt,ticker,direction,raw,strategy_id) VALUES (%s,%s,'long',%s::jsonb,%s)",
            (signal_dt, ticker, json.dumps({"close": "100", "invalidation": "99", "target_r": "1", "max_hold_days": 1}), strategy_id),
        )
        conn.execute(
            "INSERT INTO prices(ticker,dt,open,high,low,close,volume) VALUES (%s,%s,100,101.2,99.5,101.1,1000000)",
            (ticker, signal_dt + timedelta(days=1)),
        )

        result = run_setup_outcome_strategy_revalidation(
            conn,
            strategy_name=strategy_name,
            as_of=signal_dt + timedelta(days=2),
        )
        state = conn.execute("SELECT status FROM strategies WHERE id=%s", (strategy_id,)).fetchone()

        conn.execute("DELETE FROM research_log WHERE hypothesis LIKE %s", (f"%{strategy_name}",))
        conn.execute("DELETE FROM backtests WHERE strategy_id=%s", (strategy_id,))
        conn.execute("DELETE FROM signals WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM prices WHERE ticker=%s", (ticker,))
        conn.execute("DELETE FROM strategies WHERE id=%s", (strategy_id,))

    assert result["passed"] is False
    assert result["authorized"] is False
    assert result["reactivated"] is False
    assert state[0] == "candidate"


def test_approved_gate_normalizer_rejects_altered_evaluator_identity():
    from eod_monitoring import _normalize_approved_setup_gate

    complete_gate = {
        "passed": True,
        "validation_mode": "underlying_setup_outcome_revalidation",
        "gate_definition_version": 1,
        "thresholds": {
            "min_sample": 100,
            "min_oos_sample": 25,
            "min_hit_rate": "0.55",
            "min_oos_hit_rate": "0.50",
            "max_stop_rate": "0.45",
            "min_median_mfe_r": "1.0",
            "oos_fraction": "0.25",
        },
    }
    assert _normalize_approved_setup_gate(complete_gate) is not None
    assert _normalize_approved_setup_gate({**complete_gate, "validation_mode": "different_evaluator"}) is None
    assert _normalize_approved_setup_gate({**complete_gate, "gate_definition_version": 2}) is None
    assert _normalize_approved_setup_gate({**complete_gate, "gate_definition_version": True}) is None
    assert _normalize_approved_setup_gate({"passed": True, "thresholds": complete_gate["thresholds"]}) is None
    assert _normalize_approved_setup_gate({**complete_gate, "thresholds": "not-a-mapping"}) is None
    extra_threshold_gate = {**complete_gate, "thresholds": {**complete_gate["thresholds"], "unknown_threshold": 1}}
    assert _normalize_approved_setup_gate(extra_threshold_gate) is None
    bool_count_gate = {**complete_gate, "thresholds": {**complete_gate["thresholds"], "min_sample": True}}
    fractional_count_gate = {**complete_gate, "thresholds": {**complete_gate["thresholds"], "min_sample": 100.5}}
    assert _normalize_approved_setup_gate(bool_count_gate) is None
    assert _normalize_approved_setup_gate(fractional_count_gate) is None


def test_gate_pass_requires_valid_approved_definition():
    from eod_monitoring import _approved_gate_passed

    assert _approved_gate_passed({"passed": True}, None) is False
    assert _approved_gate_passed({"passed": True}, {"thresholds": {}}) is True
    assert _approved_gate_passed({"passed": False}, {"thresholds": {}}) is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, "intrabar_low"), ("", "intrabar_low"), ("intrabar_low", "intrabar_low"), ("close_below_breakout_level", "close_below"), ("unknown", None), (False, None)],
)
def test_stop_mode_parser_rejects_unknown_explicit_rules(value, expected):
    from eod_monitoring import _parse_stop_mode

    assert _parse_stop_mode(value) == expected


@pytest.mark.parametrize("value", [0, False, 1.5, "", "abc", "01", 61])
def test_max_hold_parser_rejects_explicit_invalid_or_noncanonical_values(value):
    from eod_monitoring import _parse_max_hold_days

    assert _parse_max_hold_days(value) is None


@pytest.mark.parametrize("value", [0, False, "", "NaN", "Infinity", 10.01])
def test_target_r_parser_rejects_explicit_invalid_values(value):
    from eod_monitoring import _parse_target_r

    assert _parse_target_r(value) is None


def test_signal_value_selection_does_not_fallback_when_explicit_invalid_value_is_supplied():
    from eod_monitoring import _configured_signal_value

    assert _configured_signal_value({"target_r": 0}, {"target_r": "1"}, "target_r", "1") == 0
    assert _configured_signal_value({}, {"target_r": "1"}, "target_r", "2") == "1"
    assert _configured_signal_value({}, {}, "target_r", "2") == "2"


def test_strategy_revalidation_treats_non_object_metadata_as_invalid_without_aborting():
    import psycopg
    from eod_monitoring import run_setup_outcome_strategy_revalidation

    strategy_name = "unit_scalar_strategy_metadata"
    with psycopg.connect("dbname=wolfy user=root host=/var/run/postgresql") as conn:
        conn.execute("DELETE FROM research_log WHERE hypothesis LIKE %s", (f"%{strategy_name}",))
        conn.execute("DELETE FROM backtests WHERE strategy_id IN (SELECT id FROM strategies WHERE name=%s)", (strategy_name,))
        conn.execute("DELETE FROM strategies WHERE name=%s", (strategy_name,))
        strategy_id = conn.execute(
            "INSERT INTO strategies(name,setup_type,status,metadata) VALUES (%s,'unit','candidate','5'::jsonb) RETURNING id",
            (strategy_name,),
        ).fetchone()[0]

        result = run_setup_outcome_strategy_revalidation(
            conn,
            strategy_name=strategy_name,
            as_of=date(2026, 8, 19),
        )

        conn.execute("DELETE FROM research_log WHERE hypothesis LIKE %s", (f"%{strategy_name}",))
        conn.execute("DELETE FROM backtests WHERE strategy_id=%s", (strategy_id,))
        conn.execute("DELETE FROM strategies WHERE id=%s", (strategy_id,))

    assert result["passed"] is False
    assert result["authorized"] is False
    assert result["status"] == "candidate"
