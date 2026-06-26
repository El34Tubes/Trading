#!/usr/bin/env python3
"""End-to-end smoke runner for Wolfy's accountability loop.

The runner is intentionally fixture/SQLite-first by default so it can prove the
scanner -> promotion -> pending_review logger -> Sentinel -> paper engine path
without placing trades or writing live Postgres rows.  It patches the
recommendation logger's Postgres write during the smoke and captures Sentinel
review payloads in memory; production cron jobs still use the underlying helpers
normally.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

import recommendation_logger
from lead_promotion_gate import promote_alpha_leads
from paper_portfolio import ensure_paper_tables, grade_open_trades, open_approved_recommendations
from sentinel_reviews import review_pending_recommendations

DEFAULT_ENTRY_QUOTES = {
    "MSFT": {"date": "2026-06-02", "close": 448.0, "high": 449.0, "low": 442.0, "source": "fixture_delayed_quote"}
}
DEFAULT_EXIT_QUOTES = {
    "MSFT": {"date": "2026-06-07", "close": 476.0, "high": 478.0, "low": 440.0, "source": "fixture_delayed_quote"}
}


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _seed_fixture_candidate_if_needed(db_path: Path, as_of: str | None) -> None:
    """Create a minimal deterministic fixture when the supplied smoke DB is empty.

    The CLI is meant to be a self-contained smoke test. If operators pass a new
    temporary path, seed one complete MSFT lead so the end-to-end path exercises
    promotion, Sentinel review, paper open, and outcome grading instead of
    failing on missing fixture tables.
    """
    recommendation_logger.ensure_recommendations_table(db_path)
    con = sqlite3.connect(db_path)
    try:
        if _table_exists(con, "alpha_leads") and con.execute("SELECT COUNT(*) FROM alpha_leads").fetchone()[0] > 0:
            return
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS scanner_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              run_time TEXT NOT NULL DEFAULT (datetime('now')),
              data_source TEXT NOT NULL,
              universe TEXT,
              notes TEXT
            );
            CREATE TABLE IF NOT EXISTS scanner_results (
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
            CREATE TABLE IF NOT EXISTS alpha_leads (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              report_id INTEGER,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              updated_at TEXT NOT NULL DEFAULT (datetime('now')),
              ticker TEXT NOT NULL,
              lead_type TEXT NOT NULL,
              title TEXT NOT NULL,
              thesis TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'new',
              evidence_quality_score REAL NOT NULL DEFAULT 0.0,
              evidence_count INTEGER NOT NULL DEFAULT 0,
              highest_source_quality REAL NOT NULL DEFAULT 0.0,
              suspicious_action TEXT NOT NULL DEFAULT 'clear',
              suspicious_flags_json TEXT NOT NULL DEFAULT '[]',
              catalyst_window TEXT,
              social_context TEXT,
              filing_context TEXT,
              insider_context TEXT,
              complete_ticket INTEGER NOT NULL DEFAULT 0,
              recommendation_id INTEGER,
              next_research_question TEXT,
              raw_payload_json TEXT NOT NULL DEFAULT '{}',
              source_fingerprint TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS alpha_lead_evidence (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              lead_id INTEGER NOT NULL REFERENCES alpha_leads(id) ON DELETE CASCADE,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              evidence_type TEXT NOT NULL,
              source_title TEXT,
              source_url TEXT,
              source_published_at TEXT,
              quote_or_fact TEXT NOT NULL,
              quality_score REAL NOT NULL DEFAULT 0.5,
              relevance_score REAL NOT NULL DEFAULT 0.5,
              notes TEXT,
              source_fingerprint TEXT NOT NULL,
              UNIQUE(lead_id, source_fingerprint)
            );
            CREATE TABLE IF NOT EXISTS strategy_rules(id INTEGER PRIMARY KEY AUTOINCREMENT, rule TEXT, rationale TEXT, status TEXT DEFAULT 'active');
            CREATE TABLE IF NOT EXISTS knowledge_notes(id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT, content TEXT, source_id INTEGER, confidence TEXT, tags TEXT, created_at TEXT DEFAULT (datetime('now')));
            CREATE TABLE IF NOT EXISTS yang_reviews (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              recommendation_id INTEGER NOT NULL DEFAULT 0,
              alpha_lead_id INTEGER,
              ticker TEXT NOT NULL,
              wolfy_alpha_thesis TEXT NOT NULL,
              technical_status TEXT NOT NULL,
              entry_trigger TEXT NOT NULL,
              entry_zone TEXT,
              stop_invalidation TEXT NOT NULL,
              target_exit_plan TEXT NOT NULL,
              atr REAL,
              r_multiple REAL,
              trend_read TEXT,
              relative_strength_read TEXT,
              volume_read TEXT,
              notes TEXT,
              raw_payload_json TEXT NOT NULL
            );
            """
        )
        run_id = con.execute(
            "INSERT INTO scanner_runs(run_time,data_source,universe,notes) VALUES (?,?,?,?)",
            (as_of or "2026-06-01T18:00:00+00:00", "fixture", "unit", "fresh"),
        ).lastrowid
        lead_id = con.execute(
            """INSERT INTO alpha_leads(ticker,lead_type,title,thesis,status,evidence_quality_score,evidence_count,highest_source_quality,suspicious_action,suspicious_flags_json,catalyst_window,social_context,filing_context,insider_context,next_research_question,raw_payload_json,source_fingerprint)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("MSFT", "filing_catalyst", "MSFT alpha promotion candidate", "Cloud/AI operating leverage plus a confirmed enterprise AI catalyst; not just price momentum.", "new", 0.86, 3, 0.92, "clear", "[]", "next 2-8 weeks", "constructive but not promotional", "10-Q supports AI/cloud margin expansion", "no conflict flagged", "validate trigger and earnings date", "{}", "accountability-smoke-msft"),
        ).lastrowid
        con.execute(
            """INSERT INTO scanner_results(run_id,ticker,score,data_date,close,r5,r20,r60,vs20,vs50,atr,avg_volume,high20,low20,extension_penalty,liquidity_pass)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, "MSFT", 82.0, "2026-06-01", 440.0, 3.0, 8.0, 15.0, 4.0, 7.0, 8.5, 25000000, 446.0, 410.0, 0.1, 1),
        )
        con.execute(
            "INSERT INTO alpha_lead_evidence(lead_id,evidence_type,source_title,source_url,quote_or_fact,quality_score,relevance_score,source_fingerprint) VALUES (?,?,?,?,?,?,?,?)",
            (lead_id, "filing", "fixture", "https://example.test/source", "Enterprise AI backlog and cloud margins improved.", 0.9, 0.9, "accountability-smoke-ev-msft"),
        )
        con.execute(
            """INSERT INTO yang_reviews(alpha_lead_id,ticker,wolfy_alpha_thesis,technical_status,entry_trigger,entry_zone,stop_invalidation,target_exit_plan,atr,r_multiple,trend_read,relative_strength_read,volume_read,notes,raw_payload_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (lead_id, "MSFT", "Alpha thesis confirmed", "wait_for_trigger", "Daily close above 446 on volume above 20-day average.", "440-446", "Close below 428 or failed reclaim of 50DMA.", "First target 475; trail below rising 20DMA after 1R.", 8.5, 2.2, "Above rising 50/200DMA", "Outperforming SPY", "Needs trigger volume", "Tactical trigger only", "{}"),
        )
        con.commit()
    finally:
        con.close()


def _count(con: sqlite3.Connection, table: str) -> int:
    allowed = {"alpha_leads", "recommendations", "paper_trades", "recommendation_outcomes"}
    if table not in allowed:
        raise ValueError(f"count table not allowlisted: {table}")
    exists = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if exists is None:
        return 0
    return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _status_count(con: sqlite3.Connection, table: str, status: str) -> int:
    allowed = {"alpha_leads", "recommendations", "paper_trades"}
    if table not in allowed:
        raise ValueError(f"status table not allowlisted: {table}")
    exists = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if exists is None:
        return 0
    return int(con.execute(f"SELECT COUNT(*) FROM {table} WHERE lower(COALESCE(status,''))=lower(?)", (status,)).fetchone()[0])


def _snapshot(db_path: str | Path) -> dict[str, int]:
    con = sqlite3.connect(db_path)
    try:
        return {
            "alpha_leads_converted": _status_count(con, "alpha_leads", "converted_to_recommendation"),
            "recommendations": _count(con, "recommendations"),
            "recommendations_pending_review": _status_count(con, "recommendations", "pending_review"),
            "recommendations_approved": _status_count(con, "recommendations", "approved"),
            "paper_trades": _count(con, "paper_trades"),
            "paper_trades_closed": _status_count(con, "paper_trades", "closed"),
            "recommendation_outcomes": _count(con, "recommendation_outcomes"),
        }
    finally:
        con.close()


def _delta(after: Mapping[str, int], before: Mapping[str, int], key: str) -> int:
    return int(after.get(key, 0)) - int(before.get(key, 0))


def run_accountability_loop_smoke(
    db_path: str | Path,
    *,
    as_of: str | None = None,
    entry_quotes: Mapping[str, Mapping[str, Any]] | None = None,
    exit_quotes: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run a safe end-to-end accountability-loop smoke against a fixture DB.

    Writes are limited to the supplied SQLite database. Postgres recommendation
    writes are stubbed and Sentinel review payloads are captured in memory.
    """
    db_path = Path(db_path)
    _seed_fixture_candidate_if_needed(db_path, as_of)
    ensure_paper_tables(db_path)
    before = _snapshot(db_path)
    sentinel_pg_rows: list[dict[str, Any]] = []
    recommendation_pg_rows: list[dict[str, Any]] = []

    original_pg_writer = recommendation_logger.persist_recommendation_postgres

    def capture_recommendation_pg(ticket: Mapping[str, Any], validation: Mapping[str, Any], notes: Mapping[str, Any], dsn: str | None = None) -> int:
        recommendation_pg_rows.append({"ticket": dict(ticket), "validation": dict(validation), "notes": dict(notes), "dsn": dsn})
        return len(recommendation_pg_rows)

    try:
        recommendation_logger.persist_recommendation_postgres = capture_recommendation_pg
        promotion = promote_alpha_leads(db_path, dry_run=False, as_of=as_of)
    finally:
        recommendation_logger.persist_recommendation_postgres = original_pg_writer

    after_promotion = _snapshot(db_path)
    sentinel = review_pending_recommendations(db_path, pg_writer=sentinel_pg_rows.extend)
    after_sentinel = _snapshot(db_path)
    paper_open = open_approved_recommendations(db_path, quotes=entry_quotes or DEFAULT_ENTRY_QUOTES, dry_run=False)
    after_open = _snapshot(db_path)
    paper_grade = grade_open_trades(db_path, quotes=exit_quotes or DEFAULT_EXIT_QUOTES, dry_run=False)
    after_grade = _snapshot(db_path)

    rows = {
        "alpha_leads_converted": _delta(after_promotion, before, "alpha_leads_converted"),
        "recommendations_pending_review_created": _delta(after_promotion, before, "recommendations_pending_review"),
        "sentinel_reviews_captured": len(sentinel_pg_rows),
        "recommendations_approved": _delta(after_sentinel, after_promotion, "recommendations_approved"),
        "paper_trades_opened": _delta(after_open, after_sentinel, "paper_trades"),
        "recommendation_outcomes_created": _delta(after_grade, before, "recommendation_outcomes"),
        "paper_trades_closed": _delta(after_grade, after_open, "paper_trades_closed"),
    }
    return {
        "safe_mode": "sqlite_fixture_with_captured_postgres_payloads",
        "db_path": str(db_path),
        "promotion": promotion,
        "recommendation_pg_rows_captured": len(recommendation_pg_rows),
        "sentinel": sentinel,
        "sentinel_pg_rows_captured": sentinel_pg_rows,
        "paper_open": paper_open,
        "paper_grade": paper_grade,
        "rows_created_or_updated": rows,
        "snapshots": {"before": before, "after_promotion": after_promotion, "after_sentinel": after_sentinel, "after_open": after_open, "after_grade": after_grade},
        "next_autonomous_cron_cycle": "scanner/Alpha Search create leads; promotion gate converts complete fresh leads to pending_review; Sentinel persists reviews and status updates; paper engine opens/grades approved paper-only trades from delayed/free quotes.",
    }


def _load_quote_map(path: str | None) -> dict[str, dict[str, Any]] | None:
    if not path:
        return None
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise SystemExit("quote file must be a JSON object keyed by ticker")
    return {str(k).upper(): dict(v) for k, v in data.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Wolfy accountability loop smoke test against a supplied SQLite fixture DB.")
    parser.add_argument("--db", required=True, help="SQLite fixture DB path; do not point this at live wolfy.db unless you intend safe tagged smoke writes")
    parser.add_argument("--as-of", help="Promotion freshness timestamp")
    parser.add_argument("--entry-quotes-file", help="JSON quote map for opening paper trades")
    parser.add_argument("--exit-quotes-file", help="JSON quote map for grading paper trades")
    args = parser.parse_args(argv)
    result = run_accountability_loop_smoke(
        args.db,
        as_of=args.as_of,
        entry_quotes=_load_quote_map(args.entry_quotes_file),
        exit_quotes=_load_quote_map(args.exit_quotes_file),
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
