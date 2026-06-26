#!/usr/bin/env python3
"""End-to-end smoke coverage for Wolfy's accountability loop."""
from __future__ import annotations

import json
import sqlite3

from accountability_loop_smoke import run_accountability_loop_smoke
from paper_portfolio import ensure_paper_tables
from test_lead_promotion_gate import add_evidence, add_yang, insert_alpha, insert_scanner, make_db


def test_accountability_loop_promotes_reviews_opens_and_grades_with_fixture_db(tmp_path):
    db = make_db(tmp_path)
    ensure_paper_tables(db)
    con = sqlite3.connect(db)
    lead_id = insert_alpha(con, ticker="MSFT")
    insert_scanner(con, ticker="MSFT", close=440.0, high20=446.0, low20=410.0)
    add_evidence(con, lead_id)
    add_yang(con, lead_id, ticker="MSFT")
    con.commit()
    con.close()

    result = run_accountability_loop_smoke(
        db,
        as_of="2026-06-01T18:00:00+00:00",
        entry_quotes={"MSFT": {"date": "2026-06-02", "close": 448.0, "high": 449.0, "low": 442.0}},
        exit_quotes={"MSFT": {"date": "2026-06-07", "close": 476.0, "high": 478.0, "low": 440.0}},
    )

    assert result["rows_created_or_updated"] == {
        "alpha_leads_converted": 1,
        "recommendations_pending_review_created": 1,
        "sentinel_reviews_captured": 1,
        "recommendations_approved": 1,
        "paper_trades_opened": 1,
        "recommendation_outcomes_created": 2,
        "paper_trades_closed": 1,
    }
    assert result["promotion"]["summary"]["pending_review"] == 1
    assert result["sentinel"]["decisions"] == {"1": "approved"}
    assert result["paper_open"]["opened"] == 1
    assert result["paper_grade"]["closed"] == 1

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    lead = con.execute("SELECT status, complete_ticket, recommendation_id FROM alpha_leads WHERE id=?", (lead_id,)).fetchone()
    rec = con.execute("SELECT id,status,notes FROM recommendations").fetchone()
    trade = con.execute("SELECT status,exit_reason,pnl,r_multiple FROM paper_trades WHERE recommendation_id=?", (rec["id"],)).fetchone()
    outcomes = con.execute("SELECT entry_triggered,hit_target,hit_stop FROM recommendation_outcomes WHERE recommendation_id=? ORDER BY id", (rec["id"],)).fetchall()
    con.close()

    assert dict(lead) == {"status": "converted_to_recommendation", "complete_ticket": 1, "recommendation_id": rec["id"]}
    assert rec["status"] == "approved"
    assert json.loads(rec["notes"])["sentinel_review"]["decision"] == "approved"
    assert dict(trade) == {"status": "closed", "exit_reason": "target", "pnl": 27.0, "r_multiple": 1.35}
    assert [tuple(row) for row in outcomes] == [(1, 0, 0), (1, 1, 0)]
