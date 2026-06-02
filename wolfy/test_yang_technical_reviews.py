import json
import sqlite3
from pathlib import Path

import pytest

from yang_technical_reviews import (
    ensure_yang_review_tables,
    eligible_yang_candidates,
    persist_yang_review,
)


def make_db(tmp_path: Path) -> Path:
    db = tmp_path / "wolfy.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE recommendations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          report_id INTEGER,
          timestamp TEXT NOT NULL DEFAULT (datetime('now')),
          ticker TEXT NOT NULL,
          action TEXT NOT NULL,
          recommendation_type TEXT NOT NULL,
          thesis TEXT,
          setup_type TEXT,
          entry_zone TEXT,
          entry_trigger TEXT,
          stop TEXT,
          target TEXT,
          risk_reward TEXT,
          confidence TEXT,
          position_size_suggestion TEXT,
          holding_period TEXT,
          status TEXT NOT NULL DEFAULT 'watching',
          notes TEXT
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
        """
    )
    con.commit()
    con.close()
    ensure_yang_review_tables(db)
    return db


def insert_rec(con, **overrides):
    data = {
        "ticker": "MSFT",
        "action": "buy",
        "recommendation_type": "equity",
        "thesis": "Wolfy alpha thesis: cloud/AI compounder with improving relative strength.",
        "setup_type": "pullback",
        "entry_zone": "440-445",
        "entry_trigger": "close above 446",
        "stop": "close below 428",
        "target": "475 then trail",
        "risk_reward": "2.2R",
        "confidence": "medium",
        "position_size_suggestion": "risk <= 0.75% of $5k",
        "holding_period": "2-6 weeks",
        "status": "pending_review",
        "notes": json.dumps({"validator": "test"}),
    }
    data.update(overrides)
    cols = ",".join(data)
    placeholders = ",".join("?" for _ in data)
    cur = con.execute(f"INSERT INTO recommendations({cols}) VALUES ({placeholders})", tuple(data.values()))
    return cur.lastrowid


def insert_alpha(con, rec_id=None, **overrides):
    data = {
        "ticker": "MSFT",
        "lead_type": "filing_catalyst",
        "title": "MSFT alpha support",
        "thesis": "Alpha lead thesis supporting the Wolfy recommendation.",
        "status": "converted_to_recommendation",
        "evidence_quality_score": 0.82,
        "evidence_count": 3,
        "highest_source_quality": 0.9,
        "suspicious_action": "clear",
        "suspicious_flags_json": "[]",
        "complete_ticket": 1,
        "recommendation_id": rec_id,
        "raw_payload_json": "{}",
        "source_fingerprint": f"alpha-{rec_id or 'unlinked'}",
    }
    data.update(overrides)
    cols = ",".join(data)
    placeholders = ",".join("?" for _ in data)
    cur = con.execute(f"INSERT INTO alpha_leads({cols}) VALUES ({placeholders})", tuple(data.values()))
    return cur.lastrowid


def test_eligible_candidates_require_wolfy_alpha_thesis(tmp_path):
    db = make_db(tmp_path)
    con = sqlite3.connect(db)
    with_thesis = insert_rec(con)
    insert_alpha(con, rec_id=with_thesis)
    insert_rec(con, ticker="AAPL", thesis="", status="pending_review")
    con.commit()
    con.close()

    candidates = eligible_yang_candidates(db)

    assert [c["recommendation_id"] for c in candidates] == [with_thesis]
    assert candidates[0]["alpha_lead_id"] is not None
    assert candidates[0]["wolfy_alpha_thesis"].startswith("Wolfy alpha thesis")


def test_persist_yang_review_links_recommendation_and_alpha_lead(tmp_path):
    db = make_db(tmp_path)
    con = sqlite3.connect(db)
    rec_id = insert_rec(con)
    alpha_id = insert_alpha(con, rec_id=rec_id)
    con.commit()
    con.close()

    result = persist_yang_review(
        db,
        {
            "recommendation_id": rec_id,
            "alpha_lead_id": alpha_id,
            "ticker": "MSFT",
            "wolfy_alpha_thesis": "Wolfy alpha thesis: cloud/AI compounder.",
            "technical_status": "wait_for_trigger",
            "entry_trigger": "Daily close above 446 on volume above 20-day average.",
            "entry_zone": "440-446",
            "stop_invalidation": "Close below 428 or failed reclaim of 50DMA.",
            "target_exit_plan": "First target 475; trail below rising 20DMA after 1R.",
            "atr": 8.5,
            "r_multiple": 2.2,
            "trend_read": "Above rising 50/200DMA.",
            "relative_strength_read": "Outperforming SPY over 20 sessions.",
            "volume_read": "Needs expansion on trigger.",
            "notes": "No Yang action until trigger fires.",
        },
    )

    assert result["review_id"] == 1
    assert result["status"] == "wait_for_trigger"
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM yang_reviews").fetchone()
    con.close()
    assert row["recommendation_id"] == rec_id
    assert row["alpha_lead_id"] == alpha_id
    assert row["ticker"] == "MSFT"
    assert row["atr"] == pytest.approx(8.5)
    assert json.loads(row["raw_payload_json"])["technical_status"] == "wait_for_trigger"


def test_persist_yang_review_rejects_review_without_wolfy_alpha_thesis(tmp_path):
    db = make_db(tmp_path)

    with pytest.raises(ValueError, match="wolfy_alpha_thesis"):
        persist_yang_review(
            db,
            {
                "recommendation_id": 1,
                "ticker": "MSFT",
                "technical_status": "wait_for_trigger",
                "entry_trigger": "close above 446",
                "stop_invalidation": "close below 428",
                "target_exit_plan": "475 then trail",
                "atr": 8.5,
                "r_multiple": 2.2,
            },
        )
