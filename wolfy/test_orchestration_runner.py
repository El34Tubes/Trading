from __future__ import annotations

import json
from datetime import date


def test_paper_recommendation_lifecycle_writes_and_logs_approved_signal_without_broker_action():
    import psycopg
    from orchestration_runner import run_paper_recommendation_lifecycle

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
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
    with psycopg.connect(dsn) as conn:
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

    def fake_lifecycle(conn, *, signal_dt, tickers, as_of=None, max_recommendations=3, dry_run=False):
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

    rc = orchestration_runner.run_eod_features_signals(
        tickers_csv_value="SPY",
        signal_dt_value="2026-08-18",
    )

    assert rc == 0
    assert "--create-setups" in captured["cmd"]
    assert captured["lifecycle"]["signal_dt"] == date(2026, 8, 18)
    assert captured["lifecycle"]["tickers"] == ["SPY"]
    assert captured["lifecycle"]["as_of"] == date(2026, 8, 18)
    assert captured["lifecycle"]["max_recommendations"] == 3
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

    rc = orchestration_runner.run_eod_features_signals(
        tickers_csv_value="SPY",
        signal_dt_value="2026-08-18",
    )

    assert rc == 7
    assert lifecycle_called is False
