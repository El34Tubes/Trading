from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from eod_price_features import PriceBar, compute_and_store_features, ingest_price_bars


def _fixture_bars(ticker: str = "ZZBT", *, start: date = date(2026, 1, 1), n: int = 12) -> list[PriceBar]:
    bars: list[PriceBar] = []
    close = Decimal("10")
    for i in range(n):
        close += Decimal("1")
        bars.append(PriceBar(ticker, start + timedelta(days=i), close - 1, close + 1, close - 1, close, 1_000_000))
    return bars


def _cleanup(conn, ticker: str, strategy_name: str, ids: list[int] | None = None) -> None:
    strategy_id_row = conn.execute("SELECT id FROM strategies WHERE name=%s", (strategy_name,)).fetchone()
    strategy_id = strategy_id_row[0] if strategy_id_row else None
    if ids:
        conn.execute("DELETE FROM research_log WHERE backtest_id = ANY(%s)", (ids,))
        conn.execute("DELETE FROM backtests WHERE id = ANY(%s)", (ids,))
    conn.execute("DELETE FROM signals WHERE ticker=%s", (ticker,))
    if strategy_id is not None:
        conn.execute("DELETE FROM research_log WHERE backtest_id IN (SELECT id FROM backtests WHERE strategy_id=%s)", (strategy_id,))
        conn.execute("DELETE FROM backtests WHERE strategy_id=%s", (strategy_id,))
        conn.execute("DELETE FROM strategies WHERE id=%s", (strategy_id,))
    conn.execute("DELETE FROM features WHERE ticker=%s", (ticker,))
    conn.execute("DELETE FROM prices WHERE ticker=%s", (ticker,))


def test_run_backtest_logs_walk_forward_result_and_promotes_only_to_candidate():
    psycopg = pytest.importorskip("psycopg")
    from eod_backtest import ensure_backtest_schema, run_backtest

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    ticker = "ZZBT"
    strategy_name = "unit_walk_forward_candidate"
    with psycopg.connect(dsn) as conn:
        ensure_backtest_schema(conn)
        _cleanup(conn, ticker, strategy_name)
        strategy_id = conn.execute(
            "INSERT INTO strategies(name, setup_type, status, params, notes) VALUES (%s,%s,%s,%s::jsonb,%s) RETURNING id",
            (strategy_name, "trend_plus_volume_confirmation", "research_only", '{"unit": true}', "unit test"),
        ).fetchone()[0]
        ingest_price_bars(conn, _fixture_bars(ticker), source="unit-backtest")
        compute_and_store_features(
            conn,
            tickers=[ticker],
            sma_fast_window=2,
            sma_slow_window=3,
            volume_window=2,
            atr_window=2,
            min_dollar_vol=Decimal("1000"),
        )
        for bar in _fixture_bars(ticker)[3:10]:
            conn.execute(
                "INSERT INTO signals(ticker, dt, strategy_id, direction, raw) VALUES (%s,%s,%s,%s,%s::jsonb) ON CONFLICT (ticker, dt, strategy_id) DO UPDATE SET direction=EXCLUDED.direction, raw=EXCLUDED.raw",
                (ticker, bar.dt, strategy_id, "long", '{}'),
            )

        result = run_backtest(
            conn,
            strategy_name=strategy_name,
            hypothesis="rising closes should survive a tiny OOS smoke test",
            rationale="unit fixture has deterministic positive close-to-close returns",
            tickers=[ticker],
            window_start=date(2026, 1, 1),
            window_end=date(2026, 1, 12),
            oos_days=4,
            min_oos_sharpe=Decimal("0.1"),
            slippage_bps=Decimal("10"),
            commission_per_trade=Decimal("0"),
        )

        strategy_status = conn.execute("SELECT status FROM strategies WHERE id=%s", (strategy_id,)).fetchone()[0]
        backtest = conn.execute(
            "SELECT survives_oos, params, report FROM backtests WHERE id=%s",
            (result.backtest_id,),
        ).fetchone()
        research = conn.execute(
            "SELECT hypothesis, outcome, promoted FROM research_log WHERE backtest_id=%s",
            (result.backtest_id,),
        ).fetchone()
        _cleanup(conn, ticker, strategy_name, [result.backtest_id])

    assert result.survives_oos is True
    assert strategy_status == "candidate"
    assert backtest[0] is True
    assert backtest[1]["costs"]["slippage_bps"] == "10"
    assert backtest[2]["walk_forward"]["oos_days"] == 4
    assert research == ("rising closes should survive a tiny OOS smoke test", "survived_oos_candidate", True)


def test_run_backtest_rejects_reduced_costs_and_never_sets_approved():
    psycopg = pytest.importorskip("psycopg")
    from eod_backtest import ensure_backtest_schema, run_backtest

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    ticker = "ZZBTCOST"
    strategy_name = "unit_walk_forward_cost_guard"
    with psycopg.connect(dsn) as conn:
        ensure_backtest_schema(conn)
        _cleanup(conn, ticker, strategy_name)
        conn.execute(
            "INSERT INTO config(key, value) VALUES ('slippage_bps', '{\"bps\": 10}'::jsonb) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value"
        )
        conn.execute(
            "INSERT INTO strategies(name, setup_type, status, params, notes) VALUES (%s,%s,%s,%s::jsonb,%s)",
            (strategy_name, "trend_plus_volume_confirmation", "approved", '{"unit": true}', "unit test"),
        )

        with pytest.raises(ValueError, match="Slippage/cost assumptions may not be reduced"):
            run_backtest(
                conn,
                strategy_name=strategy_name,
                hypothesis="cost cheating should fail",
                rationale="unit guard",
                tickers=[ticker],
                window_start=date(2026, 1, 1),
                window_end=date(2026, 1, 12),
                slippage_bps=Decimal("5"),
            )

        run_ids = conn.execute(
            "SELECT id FROM backtests WHERE strategy_id=(SELECT id FROM strategies WHERE name=%s)",
            (strategy_name,),
        ).fetchall()
        status = conn.execute("SELECT status FROM strategies WHERE name=%s", (strategy_name,)).fetchone()[0]
        _cleanup(conn, ticker, strategy_name, [row[0] for row in run_ids])

    assert status == "approved"
