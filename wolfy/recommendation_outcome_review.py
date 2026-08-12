#!/usr/bin/env python3
"""Postgres-native paper recommendation outcome review gate.

Grades the underlying stock/ETF technical setup after a paper recommendation.
This is not broker execution, not option fill/P&L, and never places orders.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date
from decimal import Decimal
from typing import Any, Mapping, Sequence

from eod_backtest import evaluate_underlying_setup_outcome

DEFAULT_DSN = os.environ.get("WOLFY_POSTGRES_DSN", "dbname=wolfy user=root host=/var/run/postgresql")


def ensure_paper_trade_metric_columns(conn) -> None:
    """Non-destructively add paper-ledger learning metrics to Postgres."""
    for name, ddl in {
        "max_adverse_excursion": "DOUBLE PRECISION",
        "exit_efficiency": "DOUBLE PRECISION",
        "stop_distance_atr": "DOUBLE PRECISION",
    }.items():
        conn.execute(f"ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS {name} {ddl}")


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _dec(value: Any, default: Decimal | None = None) -> Decimal:
    if value is None:
        if default is None:
            raise ValueError("missing decimal value")
        return default
    return Decimal(str(value))


def _target_r(entry: Decimal, stop: Decimal, target: Decimal) -> Decimal:
    risk = entry - stop
    if risk <= 0:
        raise ValueError("stop must be below entry")
    return (target - entry) / risk


def _fetch_future_bars(conn, ticker: str, *, entry_date: date, as_of: date, max_hold_days: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT dt, open, high, low, close
        FROM prices
        WHERE ticker=%s AND dt > %s AND dt <= %s
        ORDER BY dt
        LIMIT %s
        """,
        (ticker, entry_date, as_of, max_hold_days),
    ).fetchall()
    return [{"dt": row[0], "open": row[1], "high": row[2], "low": row[3], "close": row[4]} for row in rows]


def _exit_price(entry: Decimal, stop: Decimal, target: Decimal, outcome: Mapping[str, Any], future_bars: Sequence[Mapping[str, Any]]) -> Decimal | None:
    if outcome.get("hit_target"):
        return target
    if outcome.get("hit_stop"):
        return stop
    exit_dt = outcome.get("exit_dt")
    for bar in future_bars:
        if str(bar.get("dt")) == str(exit_dt):
            return _dec(bar.get("close"), entry)
    return None


def _canonical_exit_reason(outcome: Mapping[str, Any], target_r: Decimal) -> str:
    if outcome.get("hit_target"):
        return f"target_{target_r.quantize(Decimal('0.1'))}r".replace(".0r", "_0r")
    if outcome.get("hit_stop"):
        return "stop_or_invalidation"
    return str(outcome.get("exit_reason") or "time_stop")


def _stop_distance_atr(conn, ticker: str, *, entry_date: date, entry: Decimal, stop: Decimal) -> float | None:
    row = conn.execute("SELECT atr FROM features WHERE ticker=%s AND dt=%s", (ticker, entry_date)).fetchone()
    if not row or row[0] in (None, 0):
        return None
    atr = _dec(row[0])
    if atr <= 0:
        return None
    return float((entry - stop) / atr)


def review_open_paper_trade_setups(
    conn,
    *,
    as_of: date,
    tickers: Sequence[str] | None = None,
    max_hold_days: int = 10,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Grade paper trades by underlying setup outcome and persist outcomes.

    Reads Postgres paper_trades/recommendations/prices only. It closes paper
    trades when target/stop/time-horizon outcome is known; it does not execute,
    cancel, or route real broker orders.
    """
    ensure_paper_trade_metric_columns(conn)
    params: list[Any] = [as_of]
    scope_clause = ""
    if tickers is not None:
        scope_clause = " AND pt.ticker = ANY(%s)"
        params.append([ticker.upper() for ticker in tickers])
    rows = conn.execute(
        f"""
        SELECT pt.id, pt.recommendation_id, pt.ticker, pt.entry_date, pt.entry_price,
               pt.quantity, pt.stop_price, pt.target_price, pt.status, pt.notes, r.notes
        FROM paper_trades pt
        LEFT JOIN recommendations r ON r.id::text=pt.recommendation_id
        WHERE pt.entry_date IS NOT NULL
          AND pt.entry_date < %s
          AND pt.status IN ('open','closed')
          {scope_clause}
        ORDER BY pt.entry_date, pt.id
        """,
        params,
    ).fetchall()
    outcomes_created = 0
    closed_trades = 0
    skipped_existing = 0
    blocked_incomplete = 0
    reviewed: list[dict[str, Any]] = []
    for trade_id, rec_id, ticker, entry_dt, entry_price, quantity, stop_price, target_price, status, trade_notes, rec_notes in rows:
        existing = conn.execute("SELECT id FROM recommendation_outcomes WHERE paper_trade_id=%s LIMIT 1", (str(trade_id),)).fetchone()
        if existing:
            skipped_existing += 1
            reviewed.append({"paper_trade_id": str(trade_id), "ticker": str(ticker), "status": "existing"})
            continue
        if entry_price is None or stop_price is None or target_price is None or quantity is None:
            blocked_incomplete += 1
            reviewed.append({"paper_trade_id": str(trade_id), "ticker": str(ticker), "status": "blocked_incomplete"})
            continue
        entry = _dec(entry_price)
        stop = _dec(stop_price)
        target = _dec(target_price)
        qty = _dec(quantity)
        try:
            tr = _target_r(entry, stop, target)
        except ValueError:
            blocked_incomplete += 1
            reviewed.append({"paper_trade_id": str(trade_id), "ticker": str(ticker), "status": "blocked_invalid_risk"})
            continue
        future_bars = _fetch_future_bars(conn, str(ticker), entry_date=entry_dt, as_of=as_of, max_hold_days=max_hold_days)
        if not future_bars:
            blocked_incomplete += 1
            reviewed.append({"paper_trade_id": str(trade_id), "ticker": str(ticker), "status": "blocked_no_future_bars"})
            continue
        outcome = evaluate_underlying_setup_outcome(
            signal_dt=entry_dt,
            entry=entry,
            stop=stop,
            future_bars=future_bars,
            target_r=tr,
            max_hold_days=max_hold_days,
            stop_mode="close_below" if (rec_notes or {}).get("stop_rule") == "close_below_breakout_level" else "intrabar_low",
        )
        exit_reason = _canonical_exit_reason(outcome, tr)
        exit_dt = outcome.get("exit_dt")
        exit_px = _exit_price(entry, stop, target, outcome, future_bars)
        days_held = None
        if exit_dt:
            days_held = (date.fromisoformat(str(exit_dt)) - entry_dt).days
        pnl = None if exit_px is None else (exit_px - entry) * qty
        r_multiple = None if exit_px is None else (exit_px - entry) / (entry - stop)
        mfe_r = _dec(outcome.get("mfe_r"), Decimal("0"))
        mae_r = _dec(outcome.get("mae_r"), Decimal("0"))
        exit_efficiency = None if r_multiple is None or mfe_r <= 0 else float(r_multiple / mfe_r)
        stop_distance_atr = _stop_distance_atr(conn, str(ticker), entry_date=entry_dt, entry=entry, stop=stop)
        notes = {
            **dict(outcome),
            "paper_only": True,
            "no_live_execution": True,
            "stop_distance_atr": stop_distance_atr,
            "setup_success_metric": "underlying_stock_technical_setup_not_option_fill_pnl",
            "source": "recommendation_outcome_review.py",
        }
        if not dry_run:
            conn.execute(
                """
                INSERT INTO recommendation_outcomes(recommendation_id,paper_trade_id,entry_triggered,hit_stop,hit_target,max_gain_pct,max_drawdown_pct,r_multiple,pnl,days_held,exit_reason,notes)
                VALUES (%s,%s,true,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                """,
                (
                    str(rec_id),
                    str(trade_id),
                    bool(outcome.get("hit_stop")),
                    bool(outcome.get("hit_target")),
                    float(_dec(outcome.get("mfe_pct"), Decimal("0"))),
                    float(_dec(outcome.get("mae_pct"), Decimal("0"))),
                    None if r_multiple is None else float(r_multiple),
                    None if pnl is None else float(pnl),
                    days_held,
                    exit_reason,
                    _json(notes),
                ),
            )
            if status == "open" and exit_px is not None and exit_dt is not None:
                conn.execute(
                    """
                    UPDATE paper_trades
                    SET status='closed', exit_date=%s, exit_price=%s, exit_reason=%s, pnl=%s, r_multiple=%s, days_held=%s,
                        max_adverse_excursion=%s, exit_efficiency=%s, stop_distance_atr=%s, updated_at=now()
                    WHERE id=%s
                    """,
                    (exit_dt, float(exit_px), exit_reason, None if pnl is None else float(pnl), None if r_multiple is None else float(r_multiple), days_held, float(mae_r), exit_efficiency, stop_distance_atr, trade_id),
                )
                closed_trades += 1
        outcomes_created += 1
        reviewed.append({"paper_trade_id": str(trade_id), "ticker": str(ticker), "exit_reason": exit_reason, "classification": outcome.get("classification")})
    return {
        "dry_run": dry_run,
        "as_of": as_of.isoformat(),
        "trades_reviewed": len(rows),
        "outcomes_created": 0 if dry_run else outcomes_created,
        "closed_trades": 0 if dry_run else closed_trades,
        "skipped_existing": skipped_existing,
        "blocked_incomplete": blocked_incomplete,
        "reviewed": reviewed,
        "broker_orders_created": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Review open Wolfy paper trades by underlying setup outcome")
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    import psycopg

    with psycopg.connect(args.dsn) as conn:
        result = review_open_paper_trade_setups(conn, as_of=date.fromisoformat(args.as_of), dry_run=args.dry_run)
        if not args.dry_run:
            conn.commit()
    print(json.dumps(result, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
