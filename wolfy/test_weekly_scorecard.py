import json
import sqlite3
from pathlib import Path

from recommendation_logger import ensure_recommendations_table
from paper_portfolio import ensure_paper_tables
from weekly_scorecard import build_weekly_scorecard, render_discord_report, store_weekly_scorecard_report, run_weekly_scorecard


def make_db(tmp_path: Path) -> Path:
    db = tmp_path / "wolfy.db"
    ensure_recommendations_table(db)
    ensure_paper_tables(db)
    con = sqlite3.connect(db)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          timestamp TEXT NOT NULL DEFAULT (datetime('now')),
          report_type TEXT NOT NULL,
          content TEXT NOT NULL,
          delivered_to TEXT,
          source_job_id TEXT
        )
        """
    )
    con.commit()
    con.close()
    return db


def insert_rec(con, **overrides):
    data = {
        "timestamp": "2026-06-01T13:00:00+00:00",
        "ticker": "MSFT",
        "action": "buy",
        "recommendation_type": "equity",
        "thesis": "U.S. listed AI/cloud compounder.",
        "setup_type": "breakout",
        "entry_zone": "above 446",
        "entry_trigger": "daily close above 446",
        "stop": "close below 428",
        "target": "475 then trail",
        "risk_reward": "2.2R",
        "confidence": "medium",
        "position_size_suggestion": "risk <= 0.75% of $5k paper account; one of max 3 positions",
        "holding_period": "2-6 weeks",
        "status": "approved",
        "notes": json.dumps({
            "sentinel_review": {
                "decision": "approved",
                "constraint_check": {"revision_items": [], "failures": [], "warnings": []},
                "review_notes": "Approved by deterministic Sentinel checks.",
            },
            "jonah_refs": ["rule:breakout-volume"],
        }),
    }
    data.update(overrides)
    cols = ",".join(data)
    qs = ",".join("?" for _ in data)
    cur = con.execute(f"INSERT INTO recommendations({cols}) VALUES ({qs})", tuple(data.values()))
    return cur.lastrowid


def test_weekly_scorecard_summarizes_trades_reviews_rejections_and_learning_loop(tmp_path):
    db = make_db(tmp_path)
    con = sqlite3.connect(db)
    msft = insert_rec(con, ticker="MSFT")
    nvda = insert_rec(con, ticker="NVDA")
    rejected_notes = {
        "sentinel_review": {
            "decision": "rejected",
            "constraint_check": {
                "failures": ["foreign/manipulation/government-interference risk"],
                "revision_items": [],
                "warnings": [],
            },
            "review_notes": "Rejected: foreign/manipulation/government-interference risk",
        },
        "jonah_refs": [],
    }
    insert_rec(con, ticker="BABA", status="rejected", notes=json.dumps(rejected_notes))
    revision_notes = {
        "sentinel_review": {
            "decision": "needs_revision",
            "constraint_check": {
                "failures": [],
                "revision_items": ["risk/reward below 2R minimum for swing candidate", "missing Jonah/strategy/knowledge references"],
                "warnings": [],
            },
            "review_notes": "Needs revision: risk/reward below 2R minimum for swing candidate; missing Jonah/strategy/knowledge references",
        },
        "jonah_refs": [],
    }
    insert_rec(con, ticker="AAPL", status="needs_revision", notes=json.dumps(revision_notes), risk_reward="1.5R")
    con.execute(
        "INSERT INTO paper_trades(recommendation_id,ticker,status,entry_date,entry_price,quantity,stop_price,target_price,exit_date,exit_price,exit_reason,pnl,r_multiple,days_held,max_drawdown,max_adverse_excursion,exit_efficiency,stop_distance_atr) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (msft, "MSFT", "closed", "2026-06-01", 100.0, 1.0, 95.0, 110.0, "2026-06-04", 110.0, "target", 10.0, 2.0, 3, -1.5, -0.3, 0.8, 1.25),
    )
    con.execute(
        "INSERT INTO paper_trades(recommendation_id,ticker,status,entry_date,entry_price,quantity,stop_price,target_price,exit_date,exit_price,exit_reason,pnl,r_multiple,days_held,max_drawdown) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (nvda, "NVDA", "closed", "2026-06-02", 50.0, 1.0, 47.0, 56.0, "2026-06-05", 47.0, "stop", -3.0, -1.0, 3, -3.5),
    )
    con.commit(); con.close()

    scorecard = build_weekly_scorecard(db, as_of="2026-06-08T00:00:00+00:00", lookback_days=7)

    assert scorecard["summary"]["recommendations_reviewed"] == 4
    assert scorecard["summary"]["closed_trades"] == 2
    assert scorecard["summary"]["hit_rate"] == 0.5
    assert scorecard["summary"]["avg_r"] == 0.5
    assert scorecard["summary"]["max_drawdown_r"] == -3.5
    assert scorecard["summary"]["avg_exit_efficiency"] == 0.8
    assert scorecard["summary"]["avg_stop_distance_atr"] == 1.25
    assert scorecard["closed_trades"][0]["max_adverse_excursion"] == -0.3
    assert scorecard["rejected_trade_reasons"]["foreign/manipulation/government-interference risk"] == 1
    assert scorecard["rejected_trade_reasons"]["risk/reward below 2R minimum for swing candidate"] == 1
    assert "Tighten pre-Sentinel rejection filters" in scorecard["rule_changes_needed"][0]
    assert any("Jonah" in item and "risk/reward" in item for item in scorecard["jonah_research_priorities"])


def test_report_rendering_and_storage_are_discord_ready(tmp_path):
    db = make_db(tmp_path)
    con = sqlite3.connect(db)
    rec = insert_rec(con, ticker="MSFT")
    con.execute(
        "INSERT INTO paper_trades(recommendation_id,ticker,status,entry_date,entry_price,quantity,stop_price,target_price,exit_date,exit_price,exit_reason,pnl,r_multiple,days_held,max_drawdown) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rec, "MSFT", "closed", "2026-06-01", 100.0, 1.0, 95.0, 110.0, "2026-06-04", 110.0, "target", 10.0, 2.0, 3, -1.0),
    )
    con.commit(); con.close()

    result = run_weekly_scorecard(db, as_of="2026-06-08T00:00:00+00:00", lookback_days=7, store=True)

    report = result["report"]
    assert report.startswith("Wolfy Weekly Scorecard")
    assert "Hit rate: 100.0%" in report
    assert "Avg R: 2.00R" in report
    assert "Max drawdown: -1.00R" in report
    assert "Exit efficiency:" in report
    assert result["report_id"] is not None
    con = sqlite3.connect(db)
    row = con.execute("SELECT report_type, content, delivered_to, source_job_id FROM reports WHERE id=?", (result["report_id"],)).fetchone()
    assert row == ("wolfy_weekly_scorecard", report, "discord_ready", "weekly_scorecard.py")
    con.close()


def test_store_weekly_scorecard_creates_reports_table_when_missing(tmp_path):
    db = tmp_path / "wolfy.db"
    report_id = store_weekly_scorecard_report(db, "scorecard body")

    con = sqlite3.connect(db)
    row = con.execute("SELECT id, report_type, content FROM reports").fetchone()
    assert row == (report_id, "wolfy_weekly_scorecard", "scorecard body")
    con.close()
