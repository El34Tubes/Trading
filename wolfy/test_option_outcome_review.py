from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
import uuid

import pytest

from test_db import test_connection


def _leg(symbol: str, *, expiration: str, strike: str, bid: str, ask: str, quote_at: str) -> dict:
    return {
        "symbol": symbol,
        "expiration": expiration,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "quote_at": quote_at,
        "multiplier": 100,
    }


def test_option_value_handles_long_call_spread_expiration_and_max_loss():
    from option_outcome_review import calculate_option_value

    long_leg = {"strike": "100", "multiplier": 100}
    short_leg = {"strike": "110", "multiplier": 100}

    assert calculate_option_value(
        expression="long_call", contracts=2, long_leg=long_leg,
        short_leg=None, underlying_close=Decimal("106"),
    ) == Decimal("1200")
    assert calculate_option_value(
        expression="call_debit_spread", contracts=2, long_leg=long_leg,
        short_leg=short_leg, underlying_close=Decimal("120"),
    ) == Decimal("2000")
    assert calculate_option_value(
        expression="call_debit_spread", contracts=2, long_leg=long_leg,
        short_leg=short_leg, underlying_close=Decimal("90"),
    ) == Decimal("0")


def test_review_option_outcomes_uses_exact_fresh_marks_and_is_idempotent():
    pytest.importorskip("psycopg")
    from option_outcome_review import review_option_outcomes

    ticker = f"ZZOM{uuid.uuid4().hex[:7].upper()}"
    signal_dt = date(2099, 5, 3)
    exit_dt = date(2099, 5, 6)
    entry_at = datetime(2099, 5, 3, 20, 0, tzinfo=timezone.utc)
    mark_at = datetime(2099, 5, 6, 20, 0, tzinfo=timezone.utc)
    expiration = "2099-06-19"
    long_symbol = f"{ticker}990619C00020000"
    entry_leg = _leg(long_symbol, expiration=expiration, strike="20", bid="1.90", ask="2.00", quote_at=entry_at.isoformat())
    mark_leg = _leg(long_symbol, expiration=expiration, strike="20", bid="3.00", ask="3.20", quote_at=mark_at.isoformat())
    entry_snapshot = f"ocs_{uuid.uuid4().hex}"
    mark_snapshot = f"ocs_{uuid.uuid4().hex}"

    with test_connection() as conn:
        rec_id = conn.execute(
            """INSERT INTO recommendations(ticker,action,recommendation_type,status,notes)
               VALUES (%s,'buy','long_call','paper_logged',%s::jsonb) RETURNING id""",
            (ticker, json.dumps({
                "paper_only": True, "no_live_execution": True,
                "instrument_expression": "long_call",
                "option_chain_snapshot_id": entry_snapshot,
                "option_evaluation_id": 1,
                "long_leg": entry_leg, "short_leg": None,
                "source_signal": {"close": "20", "invalidation": "19", "target": "22"},
            })),
        ).fetchone()[0]
        for snapshot_id, available_at, chain in (
            (entry_snapshot, entry_at, [entry_leg]),
            (mark_snapshot, mark_at, [mark_leg]),
        ):
            conn.execute(
                """INSERT INTO option_chain_snapshots(
                       snapshot_id,ticker,provider,source_url,fetched_at,market_at,
                       available_at,payload_sha256,chain)
                   VALUES (%s,%s,'unit-read-only','https://unit.invalid',%s,%s,%s,%s,%s::jsonb)""",
                (snapshot_id, ticker, available_at, available_at, available_at,
                 ("a" if snapshot_id == entry_snapshot else "b") * 64, json.dumps(chain)),
            )
        evaluation_id = conn.execute(
            """INSERT INTO option_structure_evaluations(
                   ticker,signal_dt,strategy_name,underlying_price,technical_target,
                   fetched_at,source,chain,evaluation,selected_structure,snapshot_id,decision_at)
               VALUES (%s,%s,'unit-outcome',20,22,%s,'unit-read-only',%s::jsonb,
                       %s::jsonb,'long_call',%s,%s) RETURNING id""",
            (ticker, signal_dt, entry_at, json.dumps([entry_leg]),
             json.dumps({"selected": {"structure": "long_call", "long_leg": entry_leg, "short_leg": None}}),
             entry_snapshot, entry_at),
        ).fetchone()[0]
        conn.execute(
            "UPDATE recommendations SET notes=jsonb_set(notes,'{option_evaluation_id}',to_jsonb(%s::bigint)) WHERE id=%s",
            (evaluation_id, rec_id),
        )
        trade_id = conn.execute(
            """INSERT INTO paper_trades(
                   recommendation_id,ticker,entry_date,entry_price,quantity,instrument,
                   stop_price,target_price,status,notes)
               VALUES (%s,%s,%s,2,2,'long_call',19,22,'open',%s::jsonb) RETURNING id""",
            (str(rec_id), ticker, signal_dt, json.dumps({
                "instrument_expression": "long_call", "max_loss": "400",
                "option_evaluation_id": evaluation_id,
                "option_chain_snapshot_id": entry_snapshot,
                "long_leg": entry_leg, "short_leg": None,
            })),
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO recommendation_outcomes(
                   recommendation_id,paper_trade_id,entry_triggered,exit_reason,notes)
               VALUES (%s,%s,true,'target_2_0r',%s::jsonb)""",
            (str(rec_id), str(trade_id), json.dumps({"exit_dt": exit_dt.isoformat(), "outcome_type": "underlying_setup"})),
        )

        first = review_option_outcomes(conn, as_of=exit_dt, tickers=[ticker])
        second = review_option_outcomes(conn, as_of=exit_dt, tickers=[ticker])
        row = conn.execute(
            """SELECT expression,status,entry_snapshot_id,exit_snapshot_id,
                      option_evaluation_id,entry_value,exit_value,max_loss,pnl,notes
                 FROM option_outcomes WHERE paper_trade_id=%s""",
            (str(trade_id),),
        ).fetchone()
        trade = conn.execute(
            "SELECT status,exit_date,pnl FROM paper_trades WHERE id=%s", (trade_id,)
        ).fetchone()

    assert first["outcomes_created"] == 1
    assert first["broker_orders_created"] == 0
    assert second["outcomes_created"] == 0
    assert second["skipped_existing"] == 1
    assert row[:5] == ("long_call", "closed", entry_snapshot, mark_snapshot, evaluation_id)
    assert tuple(Decimal(str(value)) for value in row[5:9]) == (
        Decimal("400"), Decimal("620"), Decimal("400"), Decimal("220")
    )
    assert row[9]["quote_at"] == mark_at.isoformat()
    assert row[9]["paper_only"] is True
    assert row[9]["no_live_execution"] is True
    assert trade == ("closed", exit_dt, 220.0)


def test_review_option_outcomes_blocks_missing_or_stale_marks_without_mutating_underlying():
    pytest.importorskip("psycopg")
    from option_outcome_review import review_option_outcomes

    ticker = f"ZZOB{uuid.uuid4().hex[:7].upper()}"
    signal_dt = date(2099, 7, 1)
    exit_dt = date(2099, 7, 3)
    quote_at = datetime(2099, 7, 1, 20, 0, tzinfo=timezone.utc)
    expiration = "2099-08-21"
    symbol = f"{ticker}990821C00020000"
    leg = _leg(symbol, expiration=expiration, strike="20", bid="1.90", ask="2.00", quote_at=quote_at.isoformat())
    snapshot_id = f"ocs_{uuid.uuid4().hex}"

    with test_connection() as conn:
        conn.execute(
            """INSERT INTO option_chain_snapshots(
                   snapshot_id,ticker,provider,source_url,fetched_at,market_at,
                   available_at,payload_sha256,chain)
               VALUES (%s,%s,'unit-read-only','https://unit.invalid',%s,%s,%s,%s,%s::jsonb)""",
            (snapshot_id, ticker, quote_at, quote_at, quote_at, "c" * 64, json.dumps([leg])),
        )
        evaluation_id = conn.execute(
            """INSERT INTO option_structure_evaluations(
                   ticker,signal_dt,strategy_name,underlying_price,technical_target,
                   fetched_at,source,chain,evaluation,selected_structure,snapshot_id,decision_at)
               VALUES (%s,%s,'unit-block',20,22,%s,'unit-read-only',%s::jsonb,
                       %s::jsonb,'long_call',%s,%s) RETURNING id""",
            (ticker, signal_dt, quote_at, json.dumps([leg]),
             json.dumps({"selected": {"structure": "long_call", "long_leg": leg, "short_leg": None}}),
             snapshot_id, quote_at),
        ).fetchone()[0]
        rec_id = conn.execute(
            """INSERT INTO recommendations(ticker,action,recommendation_type,status,notes)
               VALUES (%s,'buy','long_call','paper_logged',%s::jsonb) RETURNING id""",
            (ticker, json.dumps({"instrument_expression": "long_call"})),
        ).fetchone()[0]
        trade_id = conn.execute(
            """INSERT INTO paper_trades(
                   recommendation_id,ticker,entry_date,entry_price,quantity,instrument,status,notes)
               VALUES (%s,%s,%s,2,1,'long_call','open',%s::jsonb) RETURNING id""",
            (str(rec_id), ticker, signal_dt, json.dumps({
                "instrument_expression": "long_call", "max_loss": "200",
                "option_evaluation_id": evaluation_id,
                "option_chain_snapshot_id": snapshot_id,
                "long_leg": leg, "short_leg": None,
            })),
        ).fetchone()[0]
        underlying_id = conn.execute(
            """INSERT INTO recommendation_outcomes(
                   recommendation_id,paper_trade_id,entry_triggered,exit_reason,notes)
               VALUES (%s,%s,true,'time_stop',%s::jsonb) RETURNING id""",
            (str(rec_id), str(trade_id), json.dumps({"exit_dt": exit_dt.isoformat(), "governance": "unchanged"})),
        ).fetchone()[0]

        result = review_option_outcomes(conn, as_of=exit_dt, tickers=[ticker])
        underlying = conn.execute(
            "SELECT exit_reason,notes FROM recommendation_outcomes WHERE id=%s", (underlying_id,)
        ).fetchone()
        option_count = conn.execute(
            "SELECT count(*) FROM option_outcomes WHERE paper_trade_id=%s", (str(trade_id),)
        ).fetchone()[0]

    assert result["blocked_missing_mark"] == 1
    assert option_count == 0
    assert underlying == ("time_stop", {"exit_dt": exit_dt.isoformat(), "governance": "unchanged"})
