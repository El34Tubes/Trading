from __future__ import annotations

from datetime import date, timedelta

import pytest


def _cleanup(conn, tickers: list[str]) -> None:
    conn.execute("DELETE FROM recommendation_outcomes WHERE recommendation_id IN (SELECT id::text FROM recommendations WHERE ticker = ANY(%s))", (tickers,))
    conn.execute("DELETE FROM paper_trades WHERE ticker = ANY(%s)", (tickers,))
    conn.execute("DELETE FROM recommendations WHERE ticker = ANY(%s)", (tickers,))
    conn.execute("DELETE FROM prices WHERE ticker = ANY(%s)", (tickers,))


def test_review_open_paper_trade_grades_underlying_setup_and_closes_on_target():
    psycopg = pytest.importorskip("psycopg")
    from recommendation_outcome_review import review_open_paper_trade_setups

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    ticker = "ZZREV1"
    entry_dt = date(2099, 3, 1)
    with psycopg.connect(dsn) as conn:
        try:
            _cleanup(conn, [ticker])
            rec_id = conn.execute(
                """
                INSERT INTO recommendations(ticker, action, recommendation_type, status, notes)
                VALUES (%s,'buy','equity_plus_option_spread_when_data_exists','paper_logged',%s::jsonb)
                RETURNING id
                """,
                (ticker, '{"paper_only":true,"no_live_execution":true,"strategy_name":"liquid_rs_breakout_close_confirm_1r"}'),
            ).fetchone()[0]
            trade_id = conn.execute(
                """
                INSERT INTO paper_trades(recommendation_id,ticker,entry_date,entry_price,quantity,stop_price,target_price,status,data_source,notes)
                VALUES (%s,%s,%s,100,10,95,105,'open','unit-test','{}'::jsonb)
                RETURNING id
                """,
                (str(rec_id), ticker, entry_dt),
            ).fetchone()[0]
            for idx, (high, low, close) in enumerate([(102, 99, 101), (106, 100, 105)], start=1):
                conn.execute(
                    "INSERT INTO prices(ticker,dt,open,high,low,close,volume) VALUES (%s,%s,100,%s,%s,%s,1000000)",
                    (ticker, entry_dt + timedelta(days=idx), high, low, close),
                )

            result = review_open_paper_trade_setups(conn, as_of=entry_dt + timedelta(days=3), tickers=[ticker])
            trade = conn.execute("SELECT status,exit_date,exit_price,exit_reason,pnl,r_multiple,days_held FROM paper_trades WHERE id=%s", (trade_id,)).fetchone()
            outcome = conn.execute("SELECT recommendation_id,paper_trade_id,entry_triggered,hit_target,hit_stop,r_multiple,days_held,exit_reason,notes FROM recommendation_outcomes WHERE paper_trade_id=%s::text", (str(trade_id),)).fetchone()
        finally:
            _cleanup(conn, [ticker])

    assert result["outcomes_created"] == 1
    assert result["closed_trades"] == 1
    assert trade == ("closed", entry_dt + timedelta(days=2), 105.0, "target_1_0r", 50.0, 1.0, 2)
    assert outcome[0] == str(rec_id)
    assert outcome[1] == str(trade_id)
    assert outcome[2] is True
    assert outcome[3] is True
    assert outcome[4] is False
    assert outcome[5] == 1.0
    assert outcome[6] == 2
    assert outcome[7] == "target_1_0r"
    assert outcome[8]["classification"] == "successful_continuation"
    assert outcome[8]["setup_success_metric"] == "underlying_stock_technical_setup_not_option_fill_pnl"


def test_review_open_paper_trade_setups_is_idempotent():
    psycopg = pytest.importorskip("psycopg")
    from recommendation_outcome_review import review_open_paper_trade_setups

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    ticker = "ZZREV2"
    entry_dt = date(2099, 3, 1)
    with psycopg.connect(dsn) as conn:
        try:
            _cleanup(conn, [ticker])
            rec_id = conn.execute(
                "INSERT INTO recommendations(ticker, action, recommendation_type, status, notes) VALUES (%s,'buy','equity','paper_logged','{}'::jsonb) RETURNING id",
                (ticker,),
            ).fetchone()[0]
            trade_id = conn.execute(
                "INSERT INTO paper_trades(recommendation_id,ticker,entry_date,entry_price,quantity,stop_price,target_price,status,notes) VALUES (%s,%s,%s,50,5,48,52,'open','{}'::jsonb) RETURNING id",
                (str(rec_id), ticker, entry_dt),
            ).fetchone()[0]
            conn.execute("INSERT INTO prices(ticker,dt,open,high,low,close,volume) VALUES (%s,%s,50,53,49,52,1000000)", (ticker, entry_dt + timedelta(days=1)))

            first = review_open_paper_trade_setups(conn, as_of=entry_dt + timedelta(days=2), tickers=[ticker])
            second = review_open_paper_trade_setups(conn, as_of=entry_dt + timedelta(days=2), tickers=[ticker])
            outcome_count = conn.execute("SELECT count(*) FROM recommendation_outcomes WHERE paper_trade_id=%s::text", (str(trade_id),)).fetchone()[0]
        finally:
            _cleanup(conn, [ticker])

    assert first["outcomes_created"] == 1
    assert second["outcomes_created"] == 0
    assert second["skipped_existing"] == 1
    assert outcome_count == 1
