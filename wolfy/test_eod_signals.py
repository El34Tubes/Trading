from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from eod_price_features import PriceBar, compute_and_store_features, ingest_price_bars


def _bars(ticker: str, *, start: date = date(2026, 1, 1), n: int = 35, volume: int = 2_000_000) -> list[PriceBar]:
    rows: list[PriceBar] = []
    close = Decimal("20")
    for i in range(n):
        close += Decimal("0.75")
        vol = volume * (3 if i == n - 1 else 1)
        rows.append(PriceBar(ticker, start + timedelta(days=i), close - Decimal("0.5"), close + Decimal("0.5"), close - Decimal("0.75"), close, vol))
    return rows


def _cleanup(conn, tickers: list[str]) -> None:
    conn.execute("DELETE FROM setups WHERE ticker = ANY(%s)", (tickers,))
    conn.execute("DELETE FROM signals WHERE ticker = ANY(%s)", (tickers,))
    conn.execute("DELETE FROM earnings_calendar WHERE ticker = ANY(%s)", (tickers,))
    conn.execute("DELETE FROM features WHERE ticker = ANY(%s)", (tickers,))
    conn.execute("DELETE FROM prices WHERE ticker = ANY(%s)", (tickers,))


def _restore_default_strategy_statuses(conn) -> None:
    conn.execute(
        """
        UPDATE strategies
        SET status='research_only', latest_oos_verdict=NULL, last_validated=NULL
        WHERE name IN ('pead','trend_volume_vol_regime','sector_cross_sectional_momentum')
        """
    )


def test_generate_eod_signals_seeds_research_only_strategies_and_writes_deterministic_signals():
    psycopg = pytest.importorskip("psycopg")
    from eod_signals import generate_eod_signals, seed_default_strategies

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    tickers = ["ZZSIG", "ZZMOM"]
    signal_dt = date(2026, 2, 4)
    with psycopg.connect(dsn) as conn:
        try:
            seed_default_strategies(conn)
            _restore_default_strategy_statuses(conn)
            _cleanup(conn, tickers)
            for ticker in tickers:
                ingest_price_bars(conn, _bars(ticker), source="unit-eod-signals")
            compute_and_store_features(conn, tickers=tickers, sma_fast_window=3, sma_slow_window=5, volume_window=3, atr_window=3, min_dollar_vol=Decimal("1000"))
            conn.execute("INSERT INTO earnings_calendar(ticker, event_dt, session, confirmed) VALUES (%s,%s,'amc',true) ON CONFLICT (ticker,event_dt) DO UPDATE SET confirmed=EXCLUDED.confirmed", ("ZZSIG", signal_dt - timedelta(days=1)))

            result = generate_eod_signals(conn, tickers=tickers, signal_dt=signal_dt, momentum_lookback_days=20, momentum_top_n=2)
            rows = conn.execute(
                """
                SELECT st.name, st.status, s.ticker, s.direction, s.raw
                FROM signals s JOIN strategies st ON st.id=s.strategy_id
                WHERE s.ticker = ANY(%s) AND s.dt=%s
                ORDER BY st.name, s.ticker
                """,
                (tickers, signal_dt),
            ).fetchall()
        finally:
            _cleanup(conn, tickers)
            _restore_default_strategy_statuses(conn)

    assert result["signals_upserted"] >= 3
    names = {(row[0], row[1]) for row in rows}
    assert ("pead", "research_only") in names
    assert ("trend_volume_vol_regime", "research_only") in names
    assert ("sector_cross_sectional_momentum", "research_only") in names
    assert all(row[3] == "long" for row in rows)
    assert all(row[4]["gate_status"] == "research_only" for row in rows)


def test_approved_strategy_gate_creates_setups_only_for_approved_signals():
    psycopg = pytest.importorskip("psycopg")
    from eod_signals import generate_eod_signals, propose_approved_setups, seed_default_strategies

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    ticker = "ZZGATE"
    signal_dt = date(2026, 2, 4)
    with psycopg.connect(dsn) as conn:
        try:
            seed_default_strategies(conn)
            _restore_default_strategy_statuses(conn)
            _cleanup(conn, [ticker])
            ingest_price_bars(conn, _bars(ticker), source="unit-eod-gate")
            compute_and_store_features(conn, tickers=[ticker], sma_fast_window=3, sma_slow_window=5, volume_window=3, atr_window=3, min_dollar_vol=Decimal("1000"))
            conn.execute("UPDATE strategies SET status='approved' WHERE name='trend_volume_vol_regime'")
            conn.execute("UPDATE strategies SET status='research_only' WHERE name IN ('pead','sector_cross_sectional_momentum')")
            generate_eod_signals(conn, tickers=[ticker], signal_dt=signal_dt, momentum_lookback_days=20, momentum_top_n=1)

            result = propose_approved_setups(conn, signal_dt=signal_dt, for_session=signal_dt + timedelta(days=1), tickers=[ticker])
            setups = conn.execute(
                """
                SELECT st.name, st.status, se.ticker, se.status, se.thesis
                FROM setups se JOIN strategies st ON st.id=se.strategy_id
                WHERE se.ticker=%s AND se.created_dt=%s
                ORDER BY se.id
                """,
                (ticker, signal_dt),
            ).fetchall()
        finally:
            _cleanup(conn, [ticker])
            _restore_default_strategy_statuses(conn)

    assert result["setups_created"] == 1
    assert result["blocked_by_strategy_status"] >= 1
    assert [(row[0], row[1], row[2], row[3]) for row in setups] == [("trend_volume_vol_regime", "approved", ticker, "pending_review")]
    assert "approved deterministic EOD signal" in setups[0][4]
