#!/usr/bin/env python3
"""Hermes-EOD monitoring and approved-strategy revalidation loop.

This module is intentionally conservative:
- It never promotes strategies.
- It never executes trades.
- It only flags/rejects setup or position rows when deterministic database facts
  show an invalidation breach or near-term event landmine.
- It demotes approved strategies back to candidate when monthly revalidation is
  stale or the latest OOS verdict has failed.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import psycopg

DEFAULT_DSN = os.environ.get("WOLFY_POSTGRES_DSN", "dbname=wolfy user=root host=/var/run/postgresql")
DEFAULT_STALE_AFTER_DAYS = 31


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def ensure_monitoring_schema(conn) -> None:
    """Create the non-destructive tables/indexes needed by monitoring."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS eod_monitoring_events (
          id serial PRIMARY KEY,
          run_at timestamptz NOT NULL DEFAULT now(),
          as_of date NOT NULL,
          object_type text NOT NULL,
          object_id int NOT NULL,
          ticker text,
          action text NOT NULL,
          reason text NOT NULL,
          detail jsonb NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_eod_monitoring_events_as_of ON eod_monitoring_events(as_of, object_type, ticker)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS research_log (
          id serial PRIMARY KEY,
          ts timestamptz DEFAULT now(),
          hypothesis text,
          rationale text,
          backtest_id int,
          outcome text,
          promoted boolean DEFAULT false
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_research_log_ts ON research_log(ts DESC)")


def _latest_close(conn, ticker: str, as_of: date) -> tuple[date, Decimal] | None:
    row = conn.execute(
        """
        SELECT dt, close
        FROM prices
        WHERE ticker=%s AND dt <= %s AND close IS NOT NULL
        ORDER BY dt DESC
        LIMIT 1
        """,
        (ticker, as_of),
    ).fetchone()
    if not row:
        return None
    return row[0], Decimal(str(row[1]))


def _event_landmines(conn, ticker: str, as_of: date, horizon_days: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT event_dt, session, confirmed
        FROM earnings_calendar
        WHERE ticker=%s AND event_dt >= %s AND event_dt <= %s
        ORDER BY event_dt
        """,
        (ticker, as_of, as_of + timedelta(days=horizon_days)),
    ).fetchall()
    return [
        {"event_dt": row[0], "session": row[1], "confirmed": row[2]}
        for row in rows
    ]


def _risk_reasons(conn, *, ticker: str, as_of: date, invalidation: Any, event_horizon_days: int) -> tuple[list[str], dict[str, Any]]:
    reasons: list[str] = []
    detail: dict[str, Any] = {"ticker": ticker, "as_of": as_of}
    close_row = _latest_close(conn, ticker, as_of)
    if close_row:
        close_dt, close = close_row
        detail["latest_close"] = str(close)
        detail["latest_close_dt"] = close_dt
        if invalidation is not None and close <= Decimal(str(invalidation)):
            reasons.append(f"invalidation breach: close {close} <= invalidation {invalidation}")
    else:
        detail["latest_close"] = None
    events = _event_landmines(conn, ticker, as_of, event_horizon_days)
    if events:
        reasons.append("earnings/event landmine inside pre-open horizon")
        detail["events"] = events
    return reasons, detail


def _record_monitor_event(
    conn,
    *,
    as_of: date,
    object_type: str,
    object_id: int,
    ticker: str,
    action: str,
    reasons: list[str],
    detail: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO eod_monitoring_events(as_of, object_type, object_id, ticker, action, reason, detail)
        VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)
        """,
        (as_of, object_type, object_id, ticker, action, "; ".join(reasons), _json(detail)),
    )


def run_preopen_monitoring(conn, *, as_of: date | None = None, event_horizon_days: int = 1) -> dict[str, Any]:
    """Flag last-night setups and open positions for deterministic risk changes."""
    ensure_monitoring_schema(conn)
    as_of = as_of or date.today()
    setups_flagged = 0
    positions_flagged = 0

    setup_rows = conn.execute(
        """
        SELECT id, ticker, invalidation
        FROM setups
        WHERE for_session <= %s
          AND status IN ('proposed','pending_review')
        """,
        (as_of,),
    ).fetchall()
    for setup_id, ticker, invalidation in setup_rows:
        reasons, detail = _risk_reasons(conn, ticker=ticker, as_of=as_of, invalidation=invalidation, event_horizon_days=event_horizon_days)
        if not reasons:
            continue
        conn.execute("UPDATE setups SET status='rejected' WHERE id=%s", (setup_id,))
        _record_monitor_event(conn, as_of=as_of, object_type="setup", object_id=setup_id, ticker=ticker, action="rejected", reasons=reasons, detail=detail)
        setups_flagged += 1

    position_rows = conn.execute(
        """
        SELECT id, ticker, invalidation
        FROM positions
        WHERE lower(coalesce(status,'')) IN ('open','taken','active')
        """
    ).fetchall()
    for position_id, ticker, invalidation in position_rows:
        reasons, detail = _risk_reasons(conn, ticker=ticker, as_of=as_of, invalidation=invalidation, event_horizon_days=event_horizon_days)
        if not reasons:
            continue
        conn.execute("UPDATE positions SET status='flagged' WHERE id=%s", (position_id,))
        _record_monitor_event(conn, as_of=as_of, object_type="position", object_id=position_id, ticker=ticker, action="flagged", reasons=reasons, detail=detail)
        positions_flagged += 1

    return {
        "as_of": str(as_of),
        "setups_checked": len(setup_rows),
        "positions_checked": len(position_rows),
        "setups_flagged": setups_flagged,
        "positions_flagged": positions_flagged,
    }


def run_monthly_strategy_revalidation(conn, *, as_of: date | None = None, stale_after_days: int = DEFAULT_STALE_AFTER_DAYS) -> dict[str, Any]:
    """Demote stale/failed approved strategies to candidate; never promote."""
    ensure_monitoring_schema(conn)
    as_of = as_of or date.today()
    cutoff = as_of - timedelta(days=stale_after_days)
    rows = conn.execute(
        """
        SELECT id, name, latest_oos_verdict, last_validated, notes
        FROM strategies
        WHERE status='approved'
          AND (last_validated IS NULL OR last_validated < %s OR coalesce(latest_oos_verdict, false) = false)
        ORDER BY id
        """,
        (cutoff,),
    ).fetchall()
    demoted: list[dict[str, Any]] = []
    for strategy_id, name, latest_oos_verdict, last_validated, notes in rows:
        reasons: list[str] = []
        if last_validated is None:
            reasons.append("missing monthly validation date")
        elif last_validated < cutoff:
            reasons.append(f"validation stale: last_validated {last_validated} < cutoff {cutoff}")
        if latest_oos_verdict is False or latest_oos_verdict is None:
            reasons.append(f"latest OOS verdict not passing: {latest_oos_verdict}")
        reason_text = "; ".join(reasons)
        conn.execute(
            """
            UPDATE strategies
            SET status='candidate',
                notes=coalesce(notes,'') || %s::text
            WHERE id=%s
            """,
            (f"\n[{as_of}] Demoted by EOD monitoring: {reason_text}", strategy_id),
        )
        conn.execute(
            """
            INSERT INTO research_log(hypothesis, rationale, backtest_id, outcome, promoted)
            VALUES (%s,%s,NULL,'demoted_to_candidate',false)
            """,
            (f"monthly revalidation:{name}", reason_text),
        )
        demoted.append({"strategy_id": strategy_id, "name": name, "reason": reason_text, "previous_notes": notes})
    return {"as_of": str(as_of), "cutoff": str(cutoff), "strategies_checked": len(rows), "strategies_demoted": len(demoted), "demoted": demoted}


def run_monitoring_cycle(conn, *, as_of: date | None = None, stale_after_days: int = DEFAULT_STALE_AFTER_DAYS) -> dict[str, Any]:
    as_of = as_of or date.today()
    preopen = run_preopen_monitoring(conn, as_of=as_of)
    revalidation = run_monthly_strategy_revalidation(conn, as_of=as_of, stale_after_days=stale_after_days)
    return {"preopen": preopen, "monthly_revalidation": revalidation}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Wolfy EOD monitoring/revalidation checks")
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    parser.add_argument("--as-of", default=None, help="YYYY-MM-DD; defaults to today")
    parser.add_argument("--stale-after-days", type=int, default=DEFAULT_STALE_AFTER_DAYS)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    with psycopg.connect(args.dsn) as conn:
        result = run_monitoring_cycle(conn, as_of=as_of, stale_after_days=args.stale_after_days)
    actionable = result["preopen"]["setups_flagged"] + result["preopen"]["positions_flagged"] + result["monthly_revalidation"]["strategies_demoted"]
    if args.json or actionable:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
