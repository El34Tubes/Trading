#!/usr/bin/env python3
"""Fixture tests for Wolfy's alpha lead promotion gate."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from lead_promotion_gate import promote_alpha_leads
from recommendation_logger import ensure_recommendations_table


def make_db(tmp_path: Path) -> Path:
    db = tmp_path / "wolfy.db"
    ensure_recommendations_table(db)
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE scanner_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_time TEXT NOT NULL DEFAULT (datetime('now')),
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
        CREATE TABLE alpha_leads (
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
        CREATE TABLE alpha_lead_evidence (
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
        CREATE TABLE strategy_rules(id INTEGER PRIMARY KEY AUTOINCREMENT, rule TEXT, rationale TEXT, status TEXT DEFAULT 'active');
        CREATE TABLE knowledge_notes(id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT, content TEXT, source_id INTEGER, confidence TEXT, tags TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE yang_reviews (
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
    con.commit()
    con.close()
    return db


def insert_scanner(con, ticker="MSFT", run_time="2026-06-01T13:00:00+00:00", data_date="2026-06-01", **overrides):
    run_id = con.execute("INSERT INTO scanner_runs(run_time,data_source,universe,notes) VALUES (?,?,?,?)", (run_time, "fixture", "unit", "fresh")).lastrowid
    row = {
        "run_id": run_id,
        "ticker": ticker,
        "score": 82.0,
        "data_date": data_date,
        "close": 440.0,
        "r5": 3.0,
        "r20": 8.0,
        "r60": 15.0,
        "vs20": 4.0,
        "vs50": 7.0,
        "atr": 8.5,
        "avg_volume": 25000000,
        "high20": 446.0,
        "low20": 410.0,
        "extension_penalty": 0.1,
        "liquidity_pass": 1,
    }
    row.update(overrides)
    cols = ",".join(row)
    qs = ",".join("?" for _ in row)
    con.execute(f"INSERT INTO scanner_results({cols}) VALUES ({qs})", tuple(row.values()))


def insert_alpha(con, ticker="MSFT", **overrides):
    payload = overrides.pop("raw_payload", {})
    row = {
        "ticker": ticker,
        "lead_type": "filing_catalyst",
        "title": "MSFT alpha promotion candidate",
        "thesis": "Cloud/AI operating leverage plus a confirmed enterprise AI catalyst; not just price momentum.",
        "status": "new",
        "evidence_quality_score": 0.86,
        "evidence_count": 3,
        "highest_source_quality": 0.92,
        "suspicious_action": "clear",
        "suspicious_flags_json": "[]",
        "catalyst_window": "next 2-8 weeks",
        "social_context": "constructive but not promotional",
        "filing_context": "10-Q supports AI/cloud margin expansion",
        "insider_context": "no conflict flagged",
        "complete_ticket": 0,
        "next_research_question": "validate trigger and earnings date",
        "raw_payload_json": json.dumps(payload),
        "source_fingerprint": f"alpha-{ticker}-{len(payload)}-{overrides.get('status','new')}",
    }
    row.update(overrides)
    cols = ",".join(row)
    qs = ",".join("?" for _ in row)
    return con.execute(f"INSERT INTO alpha_leads({cols}) VALUES ({qs})", tuple(row.values())).lastrowid


def add_evidence(con, lead_id, evidence_type="filing", quote="Enterprise AI backlog and cloud margins improved."):
    con.execute(
        "INSERT INTO alpha_lead_evidence(lead_id,evidence_type,source_title,source_url,quote_or_fact,quality_score,relevance_score,source_fingerprint) VALUES (?,?,?,?,?,?,?,?)",
        (lead_id, evidence_type, "fixture", "https://example.test/source", quote, 0.9, 0.9, f"ev-{lead_id}-{evidence_type}"),
    )


def add_yang(con, lead_id, ticker="MSFT"):
    con.execute(
        "INSERT INTO yang_reviews(alpha_lead_id,ticker,wolfy_alpha_thesis,technical_status,entry_trigger,entry_zone,stop_invalidation,target_exit_plan,atr,r_multiple,trend_read,relative_strength_read,volume_read,notes,raw_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (lead_id, ticker, "Alpha thesis confirmed", "wait_for_trigger", "Daily close above 446 on volume above 20-day average.", "440-446", "Close below 428 or failed reclaim of 50DMA.", "First target 475; trail below rising 20DMA after 1R.", 8.5, 2.2, "Above rising 50/200DMA", "Outperforming SPY", "Needs trigger volume", "Tactical trigger only", "{}"),
    )


def test_dry_run_promotes_complete_policy_compliant_lead_without_live_write(tmp_path):
    db = make_db(tmp_path)
    con = sqlite3.connect(db)
    lead_id = insert_alpha(con)
    insert_scanner(con)
    add_evidence(con, lead_id)
    add_yang(con, lead_id)
    con.commit(); con.close()

    result = promote_alpha_leads(db, dry_run=True, as_of="2026-06-01T18:00:00+00:00")

    assert result["summary"]["pending_review"] == 1
    assert result["summary"]["live_writes"] == 0
    decision = result["decisions"][0]
    assert decision["lead_id"] == lead_id
    assert decision["classification"] == "actionable_pending_review"
    assert decision["would_call_recommendation_logger"] is True
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0] == 0
    assert con.execute("SELECT status, recommendation_id FROM alpha_leads WHERE id=?", (lead_id,)).fetchone() == ("new", None)
    con.close()


def test_live_run_logs_complete_lead_and_updates_alpha_status(tmp_path):
    db = make_db(tmp_path)
    con = sqlite3.connect(db)
    lead_id = insert_alpha(con)
    insert_scanner(con)
    add_evidence(con, lead_id)
    add_yang(con, lead_id)
    con.commit(); con.close()

    result = promote_alpha_leads(db, dry_run=False, as_of="2026-06-01T18:00:00+00:00")

    assert result["summary"]["pending_review"] == 1
    assert result["summary"]["live_writes"] == 1
    rec_id = result["decisions"][0]["recommendation_id"]
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    lead = con.execute("SELECT status, complete_ticket, recommendation_id FROM alpha_leads WHERE id=?", (lead_id,)).fetchone()
    rec = con.execute("SELECT status, entry_trigger, stop, target, risk_reward FROM recommendations WHERE id=?", (rec_id,)).fetchone()
    con.close()
    assert dict(lead) == {"status": "converted_to_recommendation", "complete_ticket": 1, "recommendation_id": rec_id}
    assert rec["status"] == "pending_review"
    assert rec["entry_trigger"] == "Daily close above 446 on volume above 20-day average."
    assert rec["stop"] == "Close below 428 or failed reclaim of 50DMA."
    assert rec["target"] == "First target 475; trail below rising 20DMA after 1R."
    assert rec["risk_reward"] == "2.2R"


def test_incomplete_or_policy_vetoed_leads_stay_watch_only_with_validation_notes(tmp_path):
    db = make_db(tmp_path)
    con = sqlite3.connect(db)
    stale_id = insert_alpha(con, ticker="AAPL", source_fingerprint="alpha-stale")
    insert_scanner(con, ticker="AAPL", run_time="2026-05-20T13:00:00+00:00", data_date="2026-05-20")
    add_evidence(con, stale_id)
    blocked_id = insert_alpha(con, ticker="BABA", suspicious_action="veto", suspicious_flags_json=json.dumps([{"flag_type":"offshore_or_opaque_risk"}]), source_fingerprint="alpha-baba", filing_context="Chinese ADR with offshore/VIE government-interference risk")
    insert_scanner(con, ticker="BABA")
    add_evidence(con, blocked_id)
    add_yang(con, blocked_id, ticker="BABA")
    weak_id = insert_alpha(con, ticker="NVDA", filing_context="", catalyst_window="", source_fingerprint="alpha-weak")
    insert_scanner(con, ticker="NVDA")
    con.commit(); con.close()

    result = promote_alpha_leads(db, dry_run=False, as_of="2026-06-01T18:00:00+00:00")

    assert result["summary"]["pending_review"] == 0
    assert result["summary"]["watch_only"] == 3
    by_id = {d["lead_id"]: d for d in result["decisions"]}
    assert "scanner data is stale" in by_id[stale_id]["validation_notes"]
    assert "manipulation/foreign/government-interference veto" in by_id[blocked_id]["validation_notes"]
    assert "technical setup/trigger missing" in by_id[weak_id]["validation_notes"]
    con = sqlite3.connect(db)
    rows = con.execute("SELECT id,status,next_research_question,recommendation_id FROM alpha_leads ORDER BY id").fetchall()
    con.close()
    assert [r[1] for r in rows] == ["watch_only", "watch_only", "watch_only"]
    assert all(r[3] is None for r in rows)
    assert "scanner data is stale" in rows[0][2]
