import json
import sqlite3
from pathlib import Path

from recommendation_logger import ensure_recommendations_table
from sentinel_reviews import review_pending_recommendations


def make_db(tmp_path: Path) -> Path:
    db = tmp_path / "wolfy.db"
    ensure_recommendations_table(db)
    return db


def insert_rec(con, **overrides):
    notes = {
        "validator": "test",
        "robinhood_assumption": "Robinhood-tradable U.S. common stock",
        "risk_notes": "U.S. listed liquid megacap; no foreign/manipulation risk seen.",
        "jonah_refs": ["strategy_rule:breakout", "knowledge_note:ai-capex"],
        "risk_flags": [],
        "suspicious_activity": {"recommended_action": "clear", "flags": []},
    }
    data = {
        "ticker": "MSFT",
        "action": "buy",
        "recommendation_type": "equity",
        "thesis": "Wolfy alpha thesis: cloud/AI compounder with improving relative strength.",
        "setup_type": "pullback",
        "entry_zone": "440-445",
        "entry_trigger": "daily close above 446 on volume confirmation",
        "stop": "close below 428",
        "target": "475 then trail",
        "risk_reward": "2.2R",
        "confidence": "medium",
        "position_size_suggestion": "risk <= 0.75% of $5k paper account; one of max 3 positions",
        "holding_period": "2-6 weeks",
        "status": "pending_review",
        "notes": json.dumps(notes),
    }
    data.update(overrides)
    cols = ",".join(data)
    placeholders = ",".join("?" for _ in data)
    cur = con.execute(f"INSERT INTO recommendations({cols}) VALUES ({placeholders})", tuple(data.values()))
    return cur.lastrowid


def test_sentinel_approves_complete_pending_review_and_persists_review(tmp_path):
    db = make_db(tmp_path)
    con = sqlite3.connect(db)
    rec_id = insert_rec(con)
    con.commit()
    con.close()
    pg_rows = []

    result = review_pending_recommendations(db, pg_writer=pg_rows.extend)

    assert result["reviewed"] == 1
    assert result["decisions"] == {str(rec_id): "approved"}
    assert pg_rows[0]["recommendation_id"] == str(rec_id)
    assert pg_rows[0]["decision"] == "approved"
    assert pg_rows[0]["constraint_check"]["passed"] is True
    con = sqlite3.connect(db)
    status = con.execute("SELECT status FROM recommendations WHERE id=?", (rec_id,)).fetchone()[0]
    con.close()
    assert status == "approved"


def test_sentinel_rejects_foreign_or_short_risk_before_status_update(tmp_path):
    db = make_db(tmp_path)
    con = sqlite3.connect(db)
    rec_id = insert_rec(
        con,
        ticker="BABA",
        action="short",
        notes=json.dumps({
            "robinhood_assumption": "ADR with China government-interference risk",
            "risk_notes": "foreign ADR manipulation/government-interference risk",
            "jonah_refs": ["knowledge_note:china-risk"],
        }),
    )
    con.commit()
    con.close()
    pg_rows = []

    result = review_pending_recommendations(db, pg_writer=pg_rows.extend)

    assert result["decisions"] == {str(rec_id): "rejected"}
    assert "long-only" in " ".join(pg_rows[0]["constraint_check"]["failures"])
    assert "foreign/manipulation" in " ".join(pg_rows[0]["constraint_check"]["failures"])
    con = sqlite3.connect(db)
    status = con.execute("SELECT status FROM recommendations WHERE id=?", (rec_id,)).fetchone()[0]
    con.close()
    assert status == "rejected"


def test_sentinel_marks_incomplete_ticket_needs_revision(tmp_path):
    db = make_db(tmp_path)
    con = sqlite3.connect(db)
    rec_id = insert_rec(con, stop="", risk_reward="1.1R", position_size_suggestion="full position")
    con.commit()
    con.close()
    pg_rows = []

    result = review_pending_recommendations(db, pg_writer=pg_rows.extend)

    assert result["decisions"] == {str(rec_id): "needs_revision"}
    checks = pg_rows[0]["constraint_check"]
    assert "missing required field: stop" in checks["revision_items"]
    assert any("risk/reward" in item for item in checks["revision_items"])
    con = sqlite3.connect(db)
    status = con.execute("SELECT status FROM recommendations WHERE id=?", (rec_id,)).fetchone()[0]
    con.close()
    assert status == "needs_revision"


def test_sentinel_dry_run_does_not_persist_or_update(tmp_path):
    db = make_db(tmp_path)
    con = sqlite3.connect(db)
    rec_id = insert_rec(con)
    con.commit()
    con.close()
    pg_rows = []

    result = review_pending_recommendations(db, dry_run=True, pg_writer=pg_rows.extend)

    assert result["reviewed"] == 1
    assert pg_rows == []
    con = sqlite3.connect(db)
    status = con.execute("SELECT status FROM recommendations WHERE id=?", (rec_id,)).fetchone()[0]
    con.close()
    assert status == "pending_review"
