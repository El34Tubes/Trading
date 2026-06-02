import datetime as dt
import sqlite3

import pytest

from wolfy_report_context import (
    format_scanner_freshness,
    get_scanner_freshness,
    latest_available_market_close_date,
)


def make_db():
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE scanner_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_time TEXT NOT NULL,
          data_source TEXT NOT NULL,
          universe TEXT,
          notes TEXT
        );
        CREATE TABLE scanner_results (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id INTEGER NOT NULL REFERENCES scanner_runs(id) ON DELETE CASCADE,
          ticker TEXT NOT NULL,
          score REAL,
          data_date TEXT,
          close REAL,
          r5 REAL, r20 REAL, r60 REAL,
          vs20 REAL, vs50 REAL,
          atr REAL,
          avg_volume REAL,
          high20 REAL,
          low20 REAL,
          extension_penalty REAL,
          liquidity_pass INTEGER,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX idx_scanner_results_run ON scanner_results(run_id, score DESC);
        """
    )
    return con


def add_run(con, run_time, ticker, score, data_date):
    run_id = con.execute(
        "INSERT INTO scanner_runs(run_time, data_source, universe, notes) VALUES(?,?,?,?)",
        (run_time, 'test', 'unit', 'test run'),
    ).lastrowid
    con.execute(
        """
        INSERT INTO scanner_results(
            run_id,ticker,score,data_date,close,r5,r20,r60,vs20,vs50,atr,avg_volume,high20,low20,extension_penalty,liquidity_pass
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (run_id, ticker, score, data_date, 100, 1, 2, 3, 4, 5, 1.2, 2_000_000, 101, 95, 0, 1),
    )
    con.commit()
    return run_id


def test_latest_available_market_close_uses_previous_business_day_before_close():
    before_close = dt.datetime(2026, 6, 1, 8, 0, tzinfo=dt.timezone.utc)  # Monday 4am ET
    assert latest_available_market_close_date(before_close) == dt.date(2026, 5, 29)


def test_latest_available_market_close_uses_same_weekday_after_close():
    after_close = dt.datetime(2026, 6, 1, 22, 0, tzinfo=dt.timezone.utc)  # Monday 6pm ET
    assert latest_available_market_close_date(after_close) == dt.date(2026, 6, 1)


def test_scanner_freshness_selects_latest_run_and_marks_fresh():
    con = make_db()
    add_run(con, '2026-06-01 12:00:00', 'OLD', 10, '2026-05-29')
    latest_run_id = add_run(con, '2026-06-01 22:05:00', 'NEW', 99, '2026-06-01')

    status = get_scanner_freshness(con, now=dt.datetime(2026, 6, 1, 22, 30, tzinfo=dt.timezone.utc))

    assert status['latest_run_id'] == latest_run_id
    assert status['status'] == 'fresh'
    assert status['action_gate'] == 'recommendations_allowed'
    assert status['candidate_count'] == 1
    assert status['latest_data_date'] == '2026-06-01'


def test_scanner_freshness_flags_stale_data_and_blocks_recommendations():
    con = make_db()
    add_run(con, '2026-06-01 22:05:00', 'STALE', 99, '2026-05-29')

    status = get_scanner_freshness(con, now=dt.datetime(2026, 6, 1, 22, 30, tzinfo=dt.timezone.utc))

    assert status['status'] == 'scanner_stale'
    assert status['action_gate'] == 'no_trade'
    assert 'older than expected market close' in status['reason']


def test_scanner_freshness_flags_run_created_before_latest_close():
    con = make_db()
    add_run(con, '2026-06-01 19:30:00', 'PRE_CLOSE', 99, '2026-06-01')  # 3:30pm ET

    status = get_scanner_freshness(con, now=dt.datetime(2026, 6, 1, 22, 30, tzinfo=dt.timezone.utc))

    assert status['status'] == 'scanner_stale'
    assert status['action_gate'] == 'no_trade'
    assert 'before expected market close timestamp' in status['reason']


def test_format_scanner_freshness_context_contains_no_trade_gate():
    con = make_db()
    add_run(con, '2026-06-01 22:05:00', 'STALE', 99, '2026-05-29')
    status = get_scanner_freshness(con, now=dt.datetime(2026, 6, 1, 22, 30, tzinfo=dt.timezone.utc))

    line = format_scanner_freshness(status)

    assert 'Scanner freshness:' in line
    assert 'status=scanner_stale' in line
    assert 'action_gate=no_trade' in line
    assert 'Wolfy must not create actionable recommendations' in line
