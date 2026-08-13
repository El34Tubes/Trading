from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest


def test_option_research_ledger_persists_full_snapshot_candidates_and_is_idempotent():
    psycopg = pytest.importorskip("psycopg")
    from options_research_ledger import ensure_options_research_schema, store_options_structure_evaluation

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    signal_dt = date(2099, 3, 2)
    chain = [{"symbol": "ZZOPT20990320C00100000", "bid": "2", "ask": "2.2", "quote_at": "2099-03-02T20:00:00Z"}]
    evaluation = {
        "status": "selected",
        "selected": {"structure": "long_call", "long_leg": chain[0], "conservative_debit": Decimal("2.15")},
        "evaluated_candidates": [{"structure": "long_call", "score": Decimal("1.2")}],
        "rejected_contracts": [],
        "paper_only": True,
        "no_live_execution": True,
        "broker_order_submitted": False,
    }
    with psycopg.connect(dsn) as conn:
        ensure_options_research_schema(conn)
        try:
            first = store_options_structure_evaluation(
                conn, ticker="ZZOPT", signal_dt=signal_dt, strategy_name="research-test",
                underlying_price=Decimal("100"), technical_target=Decimal("110"),
                fetched_at=datetime(2099, 3, 2, 20, tzinfo=timezone.utc), source="unit-read-only",
                chain=chain, evaluation=evaluation,
            )
            second = store_options_structure_evaluation(
                conn, ticker="ZZOPT", signal_dt=signal_dt, strategy_name="research-test",
                underlying_price=Decimal("100"), technical_target=Decimal("110"),
                fetched_at=datetime(2099, 3, 2, 20, tzinfo=timezone.utc), source="unit-read-only",
                chain=chain, evaluation=evaluation,
            )
            row = conn.execute("""
                SELECT source, chain, evaluation, selected_structure, paper_only,
                       no_live_execution, broker_order_submitted
                FROM option_structure_evaluations WHERE id=%s
            """, (first["evaluation_id"],)).fetchone()
            count = conn.execute("SELECT count(*) FROM option_structure_evaluations WHERE ticker='ZZOPT' AND signal_dt=%s AND strategy_name='research-test'", (signal_dt,)).fetchone()[0]
            assert first["evaluation_id"] == second["evaluation_id"]
            assert count == 1
            assert row[0] == "unit-read-only"
            assert row[1] == chain
            assert row[2]["evaluated_candidates"][0]["score"] == "1.2"
            assert row[3] == "long_call"
            assert row[4:] == (True, True, False)
        finally:
            conn.execute("DELETE FROM option_structure_evaluations WHERE ticker='ZZOPT'")
