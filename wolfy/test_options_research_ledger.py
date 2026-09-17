from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from test_db import test_connection


SIGNAL_DT = date(2099, 3, 2)
DECISION_AT = datetime(2099, 3, 2, 20, 5, tzinfo=timezone.utc)
FETCHED_AT = datetime(2099, 3, 2, 20, 1, tzinfo=timezone.utc)
MARKET_AT = datetime(2099, 3, 2, 20, 0, tzinfo=timezone.utc)
CHAIN = [
    {
        "symbol": "ZZOPT  990320C00100000",
        "underlying": "ZZOPT",
        "option_type": "call",
        "expiration": "2099-03-20",
        "strike": "100",
        "bid": "2",
        "ask": "2.2",
        "quote_at": "2099-03-02T20:00:00Z",
    }
]
EVALUATION = {
    "ticker": "ZZOPT",
    "status": "selected",
    "selected": {
        "structure": "long_call",
        "long_leg": CHAIN[0],
        "conservative_debit": Decimal("2.15"),
    },
    "evaluated_candidates": [{"structure": "long_call", "score": Decimal("1.2")}],
    "rejected_contracts": [],
    "paper_only": True,
    "no_live_execution": True,
    "broker_order_submitted": False,
}


def _store(conn, *, ticker: str = "ZZOPT", chain=CHAIN, evaluation=EVALUATION, snapshot_id=None,
           available_at: datetime = FETCHED_AT, strategy_name: str = "research-test"):
    from options_research_ledger import store_options_structure_evaluation

    return store_options_structure_evaluation(
        conn,
        ticker=ticker,
        signal_dt=SIGNAL_DT,
        strategy_name=strategy_name,
        underlying_price=Decimal("100"),
        technical_target=Decimal("110"),
        decision_at=DECISION_AT,
        fetched_at=FETCHED_AT,
        market_at=MARKET_AT,
        available_at=available_at,
        provider="unit",
        source_url="https://example.invalid/read-only/ZZOPT",
        chain=chain,
        evaluation=evaluation,
        snapshot_id=snapshot_id,
    )


def test_option_research_ledger_persists_immutable_snapshot_and_idempotent_evaluation():
    pytest.importorskip("psycopg")
    from options_research_ledger import ensure_options_research_schema

    with test_connection() as conn:
        ensure_options_research_schema(conn)
        first = _store(conn)
        second = _store(conn)
        row = conn.execute(
            """SELECT e.ticker,e.strategy_name,e.decision_at,e.selected_structure,
                      e.paper_only,e.no_live_execution,e.broker_order_submitted,
                      s.ticker,s.provider,s.source_url,s.payload_sha256,s.chain
               FROM option_structure_evaluations e
               JOIN option_chain_snapshots s ON s.snapshot_id=e.snapshot_id
               WHERE e.id=%s""",
            (first["evaluation_id"],),
        ).fetchone()
        assert first == second
        assert len(first["payload_sha256"]) == 64
        assert row[:7] == (
            "ZZOPT", "research-test", DECISION_AT, "long_call", True, True, False
        )
        assert row[7:10] == (
            "ZZOPT", "unit", "https://example.invalid/read-only/ZZOPT"
        )
        assert row[10] == first["payload_sha256"]
        assert row[11] == CHAIN
        conn.execute("SAVEPOINT immutable_snapshot")
        with pytest.raises(Exception, match="append-only"):
            conn.execute(
                "UPDATE option_chain_snapshots SET provider='tampered' WHERE snapshot_id=%s",
                (first["snapshot_id"],),
            )
        conn.execute("ROLLBACK TO SAVEPOINT immutable_snapshot")


def test_option_snapshot_identity_rejects_changed_payload_and_late_availability():
    pytest.importorskip("psycopg")
    with test_connection() as conn:
        first = _store(conn, snapshot_id="unit-fixed-snapshot")
        changed = deepcopy(CHAIN)
        changed[0]["ask"] = "9.9"
        with pytest.raises(ValueError, match="snapshot identity.*different payload"):
            _store(conn, chain=changed, snapshot_id=first["snapshot_id"])
        with pytest.raises(ValueError, match="available_at must not be after decision_at"):
            _store(conn, snapshot_id="unit-late-snapshot", available_at=DECISION_AT + timedelta(seconds=1))


@pytest.mark.parametrize(
    ("ticker", "evaluation", "match"),
    [
        ("OTHER", EVALUATION, "evaluation ticker mismatch"),
        ("ZZOPT", {**EVALUATION, "ticker": "OTHER"}, "evaluation ticker mismatch"),
    ],
)
def test_option_evaluation_rejects_ticker_or_occ_underlying_mismatch(ticker, evaluation, match):
    pytest.importorskip("psycopg")
    chain = deepcopy(CHAIN)
    with test_connection() as conn, pytest.raises(ValueError, match=match):
        _store(conn, ticker=ticker, chain=chain, evaluation=evaluation)


def test_option_evaluation_rejects_occ_underlying_mismatch():
    pytest.importorskip("psycopg")
    chain = deepcopy(CHAIN)
    chain[0]["underlying"] = "OTHER"
    with test_connection() as conn, pytest.raises(ValueError, match="OCC underlying mismatch"):
        _store(conn, chain=chain)
