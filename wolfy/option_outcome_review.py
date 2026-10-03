#!/usr/bin/env python3
"""Separate paper-only outcomes for exact option expressions.

The underlying setup ledger remains authoritative for strategy governance.  This
module grades only the selected long call or call debit spread and has no broker
adapter or live-order capability.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from typing import Any, Mapping, Sequence

DEFAULT_DSN = os.environ.get(
    "WOLFY_POSTGRES_DSN", "dbname=wolfy user=root host=/var/run/postgresql"
)
_OPTION_EXPRESSIONS = frozenset({"long_call", "call_debit_spread"})
_MAX_MARK_AGE = timedelta(minutes=30)


def _dec(value: object, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite decimal") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError(f"{field} must be a finite {'positive ' if positive else ''}decimal")
    return result


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a mapping")
    return value


def _aware(value: object, field: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be timezone-aware") from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _expiration(leg: Mapping[str, Any]) -> date:
    try:
        return date.fromisoformat(str(leg["expiration"]))
    except (KeyError, ValueError) as exc:
        raise ValueError("long leg expiration must be an ISO date") from exc


def _multiplier(leg: Mapping[str, Any]) -> Decimal:
    multiplier = _dec(leg.get("multiplier", 100), "multiplier", positive=True)
    if multiplier != 100:
        raise ValueError("only standard 100-share option contracts are supported")
    return multiplier


def calculate_option_value(
    *,
    expression: str,
    contracts: int,
    long_leg: Mapping[str, Any],
    short_leg: Mapping[str, Any] | None,
    underlying_close: Decimal,
) -> Decimal:
    """Calculate deterministic expiration settlement from underlying close."""
    if expression not in _OPTION_EXPRESSIONS:
        raise ValueError("unsupported option expression")
    if type(contracts) is not int or contracts <= 0:
        raise ValueError("contracts must be a positive integer")
    close = _dec(underlying_close, "underlying_close", positive=True)
    long_strike = _dec(long_leg.get("strike"), "long strike", positive=True)
    multiplier = _multiplier(long_leg)
    long_intrinsic = max(close - long_strike, Decimal("0"))
    if expression == "long_call":
        if short_leg is not None:
            raise ValueError("long_call cannot have a short leg")
        per_share = long_intrinsic
    else:
        short = _mapping(short_leg, "short_leg")
        short_strike = _dec(short.get("strike"), "short strike", positive=True)
        if _multiplier(short) != multiplier or short_strike <= long_strike:
            raise ValueError("call spread legs are invalid")
        per_share = min(long_intrinsic, short_strike - long_strike)
    return per_share * multiplier * contracts


def _mid(leg: Mapping[str, Any]) -> Decimal:
    bid = _dec(leg.get("bid"), "bid")
    ask = _dec(leg.get("ask"), "ask")
    if bid < 0 or ask < bid:
        raise ValueError("option mark has invalid bid/ask")
    return (bid + ask) / Decimal("2")


def _mark_value(
    *, expression: str, contracts: int, long_leg: Mapping[str, Any],
    short_leg: Mapping[str, Any] | None,
) -> Decimal:
    multiplier = _multiplier(long_leg)
    if expression == "long_call":
        if short_leg is not None:
            raise ValueError("long_call cannot have a short leg")
        per_share = _mid(long_leg)
    else:
        short = _mapping(short_leg, "short_leg")
        width = _dec(short.get("strike"), "short strike", positive=True) - _dec(
            long_leg.get("strike"), "long strike", positive=True
        )
        if width <= 0 or _multiplier(short) != multiplier:
            raise ValueError("call spread legs are invalid")
        per_share = min(max(_mid(long_leg) - _mid(short), Decimal("0")), width)
    return per_share * multiplier * contracts


def _find_mark_snapshot(
    conn,
    *,
    ticker: str,
    exit_dt: date,
    as_of: date,
    long_symbol: str,
    short_symbol: str | None,
) -> tuple[str, Mapping[str, Any], Mapping[str, Any] | None, datetime] | None:
    cutoff = datetime.combine(as_of + timedelta(days=1), time.min, tzinfo=timezone.utc)
    rows = conn.execute(
        """SELECT snapshot_id,available_at,market_at,chain
             FROM option_chain_snapshots
            WHERE ticker=%s AND available_at < %s
            ORDER BY available_at DESC,snapshot_id DESC""",
        (ticker, cutoff),
    ).fetchall()
    for snapshot_id, available_at, market_at, chain in rows:
        if not isinstance(chain, list) or not chain:
            continue
        by_symbol = {
            str(contract.get("symbol")): contract
            for contract in chain
            if isinstance(contract, Mapping)
        }
        long_mark = by_symbol.get(long_symbol)
        short_mark = by_symbol.get(short_symbol) if short_symbol else None
        if long_mark is None or (short_symbol and short_mark is None):
            continue
        try:
            quote_times = [_aware(long_mark.get("quote_at"), "quote_at")]
            if short_mark is not None:
                quote_times.append(_aware(short_mark.get("quote_at"), "quote_at"))
            if any(stamp.date() != exit_dt for stamp in quote_times):
                continue
            available = _aware(available_at, "available_at")
            market = _aware(market_at, "market_at")
            if any(stamp > available or abs(market - stamp) > _MAX_MARK_AGE for stamp in quote_times):
                continue
        except ValueError:
            continue
        return str(snapshot_id), long_mark, short_mark, max(quote_times)
    return None


def review_option_outcomes(
    conn,
    *,
    as_of: date,
    tickers: Sequence[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Grade exact options without mutating setup outcomes or governance rows."""
    if type(as_of) is not date:
        raise ValueError("as_of must be a date")
    database = conn.execute("SELECT current_database()").fetchone()[0]
    if not dry_run and database != "wolfy_test":
        raise RuntimeError("pivot option outcome writes are disabled outside wolfy_test")
    params: list[object] = []
    scope = ""
    if tickers is not None:
        scope = " AND pt.ticker=ANY(%s)"
        params.append([str(ticker).strip().upper() for ticker in tickers])
    rows = conn.execute(
        f"""SELECT pt.id,pt.recommendation_id,pt.ticker,pt.entry_date,pt.quantity,
                    pt.instrument,pt.notes,r.notes
               FROM paper_trades pt
               JOIN recommendations r ON r.id::text=pt.recommendation_id
              WHERE pt.instrument IN ('long_call','call_debit_spread') {scope}
              ORDER BY pt.entry_date,pt.id""",
        params,
    ).fetchall()
    created = skipped = blocked_mark = blocked_pending = blocked_invalid = closed_trades = 0
    reviewed: list[dict[str, Any]] = []
    for trade_id, recommendation_id, ticker, entry_dt, quantity, instrument, trade_notes, rec_notes in rows:
        trade_key = str(trade_id)
        if conn.execute(
            "SELECT 1 FROM option_outcomes WHERE paper_trade_id=%s", (trade_key,)
        ).fetchone():
            skipped += 1
            continue
        try:
            notes = _mapping(trade_notes, "trade notes")
            recommendation_notes = _mapping(rec_notes, "recommendation notes")
            expression = str(notes.get("instrument_expression") or instrument)
            if expression not in _OPTION_EXPRESSIONS or expression != instrument:
                raise ValueError("option expression mismatch")
            contracts_decimal = _dec(quantity, "quantity", positive=True)
            contracts = int(contracts_decimal)
            if Decimal(contracts) != contracts_decimal:
                raise ValueError("option quantity must be a positive integer")
            max_loss = _dec(notes.get("max_loss"), "max_loss", positive=True)
            evaluation_id = notes.get("option_evaluation_id")
            if type(evaluation_id) is not int or evaluation_id <= 0:
                raise ValueError("option_evaluation_id is required")
            entry_snapshot = str(notes.get("option_chain_snapshot_id") or "")
            long_leg = _mapping(notes.get("long_leg"), "long_leg")
            short_leg_raw = notes.get("short_leg")
            short_leg = None if short_leg_raw is None else _mapping(short_leg_raw, "short_leg")
            long_symbol = str(long_leg.get("symbol") or "")
            short_symbol = str(short_leg.get("symbol") or "") if short_leg else None
            if not entry_snapshot or not long_symbol:
                raise ValueError("exact entry provenance is required")
            if expression == "call_debit_spread" and not short_symbol:
                raise ValueError("call spread requires an exact short leg")
            evaluation = conn.execute(
                """SELECT e.ticker,e.snapshot_id,e.selected_structure,e.evaluation,s.ticker
                     FROM option_structure_evaluations e
                     JOIN option_chain_snapshots s ON s.snapshot_id=e.snapshot_id
                    WHERE e.id=%s""",
                (evaluation_id,),
            ).fetchone()
            selected = evaluation[3].get("selected") if evaluation and isinstance(evaluation[3], Mapping) else None
            if (
                evaluation is None
                or (evaluation[0], evaluation[1], evaluation[2], evaluation[4])
                != (ticker, entry_snapshot, expression, ticker)
                or not isinstance(selected, Mapping)
                or selected.get("long_leg") != long_leg
                or selected.get("short_leg") != short_leg
                or recommendation_notes.get("instrument_expression") != expression
            ):
                raise ValueError("option outcome provenance mismatch")
            expiration = _expiration(long_leg)
            if short_leg is not None and _expiration(short_leg) != expiration:
                raise ValueError("spread expiration mismatch")
        except (ValueError, TypeError):
            blocked_invalid += 1
            reviewed.append({"paper_trade_id": trade_key, "status": "blocked_invalid_provenance"})
            continue

        underlying = conn.execute(
            """SELECT exit_reason,notes FROM recommendation_outcomes
                WHERE paper_trade_id=%s AND outcome_type='underlying_setup'""",
            (trade_key,),
        ).fetchone()
        if underlying is None:
            blocked_pending += 1
            reviewed.append({"paper_trade_id": trade_key, "status": "underlying_outcome_pending"})
            continue
        underlying_notes = underlying[1] if isinstance(underlying[1], Mapping) else {}
        try:
            underlying_exit_dt = date.fromisoformat(str(underlying_notes.get("exit_dt")))
        except ValueError:
            blocked_pending += 1
            reviewed.append({"paper_trade_id": trade_key, "status": "underlying_outcome_pending"})
            continue

        exit_snapshot_id: str | None = None
        quote_at: datetime | None = None
        if as_of >= expiration and underlying_exit_dt >= expiration:
            price = conn.execute(
                """SELECT dt,close FROM prices
                    WHERE ticker=%s AND dt<=%s ORDER BY dt DESC LIMIT 1""",
                (ticker, expiration),
            ).fetchone()
            if price is None:
                blocked_mark += 1
                reviewed.append({"paper_trade_id": trade_key, "status": "blocked_missing_expiration_price"})
                continue
            try:
                exit_value = calculate_option_value(
                    expression=expression,
                    contracts=contracts,
                    long_leg=long_leg,
                    short_leg=short_leg,
                    underlying_close=_dec(price[1], "expiration close", positive=True),
                )
            except ValueError:
                blocked_invalid += 1
                continue
            exit_reason = "expiration_settlement"
            mark_provenance = {"price_dt": price[0].isoformat(), "underlying_close": str(price[1])}
        else:
            mark = _find_mark_snapshot(
                conn,
                ticker=str(ticker),
                exit_dt=underlying_exit_dt,
                as_of=as_of,
                long_symbol=long_symbol,
                short_symbol=short_symbol,
            )
            if mark is None:
                blocked_mark += 1
                reviewed.append({"paper_trade_id": trade_key, "status": "blocked_missing_mark"})
                continue
            exit_snapshot_id, long_mark, short_mark, quote_at = mark
            try:
                exit_value = _mark_value(
                    expression=expression,
                    contracts=contracts,
                    long_leg=long_mark,
                    short_leg=short_mark,
                )
            except ValueError:
                blocked_mark += 1
                continue
            exit_reason = f"underlying_{underlying[0] or 'outcome'}"
            mark_provenance = {"quote_at": quote_at.isoformat()}

        entry_value = max_loss
        pnl = max(exit_value - entry_value, -max_loss)
        outcome_notes = {
            "outcome_type": "option_expression",
            "underlying_outcome_exit_reason": underlying[0],
            "entry_snapshot_id": entry_snapshot,
            "exit_snapshot_id": exit_snapshot_id,
            "option_evaluation_id": evaluation_id,
            "paper_only": True,
            "no_live_execution": True,
            "broker_order_submitted": False,
            **mark_provenance,
        }
        if not dry_run:
            inserted = conn.execute(
                """INSERT INTO option_outcomes(
                       recommendation_id,paper_trade_id,option_evaluation_id,
                       entry_snapshot_id,exit_snapshot_id,expression,status,exit_reason,
                       expiration,entry_value,exit_value,max_loss,pnl,return_on_risk,
                       quote_at,notes,paper_only,no_live_execution,broker_order_submitted)
                   VALUES (%s,%s,%s,%s,%s,%s,'closed',%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,true,true,false)
                   ON CONFLICT(paper_trade_id) DO NOTHING RETURNING id""",
                (
                    str(recommendation_id), trade_key, evaluation_id, entry_snapshot,
                    exit_snapshot_id, expression, exit_reason, expiration, entry_value,
                    exit_value, max_loss, pnl, pnl / max_loss, quote_at,
                    json.dumps(outcome_notes, sort_keys=True),
                ),
            ).fetchone()
            if inserted is None:
                skipped += 1
                continue
            close_dt = min(underlying_exit_dt, expiration)
            conn.execute(
                """UPDATE paper_trades
                      SET status='closed',exit_date=%s,exit_price=%s,exit_reason=%s,
                          pnl=%s,r_multiple=%s,days_held=%s,updated_at=now()
                    WHERE id=%s AND status<>'closed'""",
                (
                    close_dt,
                    exit_value / Decimal(contracts * 100),
                    exit_reason,
                    pnl,
                    pnl / max_loss,
                    (close_dt - entry_dt).days,
                    trade_id,
                ),
            )
            closed_trades += 1
        created += 1
        reviewed.append({"paper_trade_id": trade_key, "status": "closed", "pnl": str(pnl)})

    return {
        "dry_run": dry_run,
        "as_of": as_of.isoformat(),
        "trades_reviewed": len(rows),
        "outcomes_created": 0 if dry_run else created,
        "closed_trades": 0 if dry_run else closed_trades,
        "skipped_existing": skipped,
        "blocked_missing_mark": blocked_mark,
        "blocked_underlying_pending": blocked_pending,
        "blocked_invalid_provenance": blocked_invalid,
        "reviewed": reviewed,
        "broker_orders_created": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Review exact paper option outcomes")
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    import psycopg

    with psycopg.connect(args.dsn) as conn:
        result = review_option_outcomes(
            conn, as_of=date.fromisoformat(args.as_of), dry_run=args.dry_run
        )
        if not args.dry_run:
            conn.commit()
    print(json.dumps(result, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
