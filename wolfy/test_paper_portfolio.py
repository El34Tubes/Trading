import json
import sqlite3
from pathlib import Path

from recommendation_logger import ensure_recommendations_table
from paper_portfolio import ensure_paper_tables, open_approved_recommendations, grade_open_trades, run_paper_engine


def make_db(tmp_path: Path) -> Path:
    db = tmp_path / "wolfy.db"
    ensure_recommendations_table(db)
    ensure_paper_tables(db)
    return db


def insert_rec(con, **overrides):
    data = {
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
        "notes": json.dumps({"sentinel_review": {"decision": "approved"}}),
    }
    data.update(overrides)
    cols = ",".join(data)
    qs = ",".join("?" for _ in data)
    cur = con.execute(f"INSERT INTO recommendations({cols}) VALUES ({qs})", tuple(data.values()))
    return cur.lastrowid


def latest_outcome(con, recommendation_id):
    con.row_factory = sqlite3.Row
    return con.execute(
        "SELECT * FROM recommendation_outcomes WHERE recommendation_id=? ORDER BY id DESC LIMIT 1",
        (recommendation_id,),
    ).fetchone()


def test_opens_only_approved_entry_triggered_trade_and_respects_max_three_positions(tmp_path):
    db = make_db(tmp_path)
    con = sqlite3.connect(db)
    rec_id = insert_rec(con)
    blocked_id = insert_rec(con, ticker="AAPL", status="needs_revision")
    # Existing open positions leave exactly one slot under the max-3 rule.
    con.execute("INSERT INTO paper_trades(recommendation_id,ticker,status,entry_price,quantity,stop_price,target_price) VALUES (99,'NVDA','open',100,1,90,120)")
    con.execute("INSERT INTO paper_trades(recommendation_id,ticker,status,entry_price,quantity,stop_price,target_price) VALUES (98,'AMD','open',50,1,45,60)")
    con.commit(); con.close()

    quotes = {"MSFT": {"date": "2026-06-01", "close": 448.0, "high": 449.0, "low": 442.0}}
    result = open_approved_recommendations(db, quotes=quotes, dry_run=False)

    assert result["opened"] == 1
    assert result["blocked_max_positions"] == 0
    con = sqlite3.connect(db)
    rows = con.execute("SELECT recommendation_id,ticker,status,entry_price,quantity,stop_price,target_price FROM paper_trades WHERE ticker='MSFT'").fetchall()
    assert rows == [(rec_id, "MSFT", "open", 448.0, 1.0, 428.0, 475.0)]
    assert con.execute("SELECT COUNT(*) FROM paper_trades WHERE recommendation_id=?", (blocked_id,)).fetchone()[0] == 0
    outcome = latest_outcome(con, rec_id)
    assert outcome["entry_triggered"] == 1
    assert json.loads(outcome["notes"])["source"] == "delayed_or_free_quote"
    con.close()


def test_blocks_opening_when_max_three_positions_already_open(tmp_path):
    db = make_db(tmp_path)
    con = sqlite3.connect(db)
    rec_id = insert_rec(con)
    for idx, ticker in enumerate(["NVDA", "AMD", "HOOD"], start=1):
        con.execute("INSERT INTO paper_trades(recommendation_id,ticker,status,entry_price,quantity,stop_price,target_price) VALUES (?,?,?,?,?,?,?)", (90+idx, ticker, "open", 100, 1, 90, 120))
    con.commit(); con.close()

    result = open_approved_recommendations(db, quotes={"MSFT": {"date": "2026-06-01", "close": 448}}, dry_run=False)

    assert result["opened"] == 0
    assert result["blocked_max_positions"] == 1
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM paper_trades WHERE recommendation_id=?", (rec_id,)).fetchone()[0] == 0
    con.close()


def test_grades_open_trade_exit_target_and_records_pnl_r_multiple_mfe_mae_days(tmp_path):
    db = make_db(tmp_path)
    con = sqlite3.connect(db)
    rec_id = insert_rec(con)
    con.execute(
        "INSERT INTO paper_trades(recommendation_id,ticker,status,entry_date,entry_price,quantity,stop_price,target_price) VALUES (?,?,?,?,?,?,?,?)",
        (rec_id, "MSFT", "open", "2026-06-01", 448.0, 1.0, 428.0, 475.0),
    )
    con.commit(); con.close()

    quotes = {"MSFT": {"date": "2026-06-06", "close": 476.0, "high": 478.0, "low": 440.0}}
    result = grade_open_trades(db, quotes=quotes, dry_run=False)

    assert result["closed"] == 1
    con = sqlite3.connect(db)
    row = con.execute("SELECT status,exit_date,exit_price,exit_reason,pnl,r_multiple,days_held,max_favorable_excursion,max_drawdown FROM paper_trades WHERE recommendation_id=?", (rec_id,)).fetchone()
    assert row == ("closed", "2026-06-06", 475.0, "target", 27.0, 1.35, 5, 30.0, -8.0)
    outcome = latest_outcome(con, rec_id)
    assert outcome["hit_target"] == 1
    assert outcome["hit_stop"] == 0
    assert outcome["max_gain_pct"] == round((478.0 - 448.0) / 448.0 * 100, 4)
    assert outcome["max_drawdown_pct"] == round((440.0 - 448.0) / 448.0 * 100, 4)
    assert outcome["r_multiple"] == 1.35
    con.close()


def test_run_paper_engine_dry_run_does_not_write(tmp_path):
    db = make_db(tmp_path)
    con = sqlite3.connect(db)
    rec_id = insert_rec(con)
    con.commit(); con.close()

    result = run_paper_engine(db, quotes={"MSFT": {"date": "2026-06-01", "close": 448}}, dry_run=True)

    assert result["dry_run"] is True
    assert result["open"]["would_open"] == 1
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM paper_trades WHERE recommendation_id=?", (rec_id,)).fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM recommendation_outcomes WHERE recommendation_id=?", (rec_id,)).fetchone()[0] == 0
    con.close()
