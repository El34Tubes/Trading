#!/usr/bin/env python3
"""Resumable Wolfy tiered EOD backfill runner.

Runs eod_price_features.massive_ingest in small commit-safe batches.
Designed for manual/background execution; prints compact progress lines.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Sequence

try:
    import psycopg
except ModuleNotFoundError:  # pragma: no cover - keep --help available without the driver
    psycopg = None

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from eod_price_features import massive_ingest  # noqa: E402

DEFAULT_DSN = os.environ.get("WOLFY_POSTGRES_DSN", "dbname=wolfy user=root host=/var/run/postgresql")
DEFAULT_TIERS = ["large_cap", "mid_cap", "small_cap"]
# Massive free-tier two-calendar-year pulls can return ~499 bars depending on
# the current trading calendar/holiday boundary. Treat 495+ bars as usable EOD
# history so resumable backfills do not re-fetch the same tickers forever.
DEFAULT_MIN_HISTORY_BARS = 495


def require_psycopg():
    if psycopg is None:  # pragma: no cover
        raise SystemExit("psycopg is required; run with: uvx --with 'psycopg[binary]' python backfill_tiered_remaining.py")
    return psycopg


def remaining_tickers(
    conn,
    tier: str,
    limit: int,
    min_history_bars: int,
    exclude: Sequence[str] | None = None,
) -> list[str]:
    """Return the next resumable backfill targets for a tier.

    ``exclude`` prevents a bounded multi-batch run from retrying the same
    still-missing/stale ticker in consecutive batches. A failed or naturally
    short ticker remains eligible on the next cron tick, but it will not consume
    both limited batches in the same run.
    """
    exclude = list(exclude or [])
    exclude_clause = ""
    params: list[object] = [tier, min_history_bars]
    if exclude:
        placeholders = ", ".join(["%s"] * len(exclude))
        exclude_clause = f"AND t.symbol NOT IN ({placeholders})"
        params.extend(exclude)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT t.symbol
        FROM universe_backfill_targets t
        LEFT JOIN (
          SELECT ticker, count(*) AS bars, max(dt) AS latest_dt
          FROM prices
          GROUP BY ticker
        ) p ON p.ticker = t.symbol
        WHERE t.active
          AND t.tier = %s
          AND coalesce(t.enabled, true)
          AND coalesce(t.backfill_enabled, true)
          AND (
            coalesce(p.bars, 0) = 0
            OR (
              coalesce(p.bars, 0) < %s
              AND coalesce(p.latest_dt, DATE '1900-01-01') < CURRENT_DATE - INTERVAL '5 days'
            )
          )
          {exclude_clause}
        ORDER BY t.priority, t.symbol
        LIMIT %s
        """,
        params,
    ).fetchall()
    return [row[0] for row in rows]


def tier_counts(conn, min_history_bars: int = DEFAULT_MIN_HISTORY_BARS) -> list[dict]:
    rows = conn.execute(
        """
        SELECT t.tier,
               count(*) AS targets,
               count(*) FILTER (WHERE coalesce(p.bars,0) >= %s) AS loaded_500,
               count(*) FILTER (WHERE coalesce(p.bars,0) > 0 AND coalesce(p.bars,0) < %s) AS partial,
               count(*) FILTER (WHERE coalesce(p.bars,0) = 0) AS missing
        FROM universe_backfill_targets t
        LEFT JOIN (
          SELECT ticker, count(*) AS bars
          FROM prices
          GROUP BY ticker
        ) p ON p.ticker = t.symbol
        WHERE t.active
        GROUP BY t.tier
        ORDER BY min(t.priority), t.tier
        """,
        (min_history_bars, min_history_bars),
    ).fetchall()
    return [
        {"tier": r[0], "targets": int(r[1]), "loaded_500": int(r[2]), "partial": int(r[3]), "missing": int(r[4])}
        for r in rows
    ]


def log_line(payload: dict) -> None:
    payload = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **payload}
    print(json.dumps(payload, sort_keys=True), flush=True)


def run(args: argparse.Namespace) -> int:
    db = require_psycopg()
    tiers: Sequence[str] = args.tiers or DEFAULT_TIERS
    deadline = time.monotonic() + args.max_runtime_seconds if args.max_runtime_seconds else None
    batches = 0
    failures = 0
    attempted_this_run: set[str] = set()
    log_line({"event": "start", "tiers": list(tiers), "batch_size": args.batch_size, "days": args.days})
    with db.connect(args.dsn) as conn:
        log_line({"event": "initial_counts", "counts": tier_counts(conn, args.min_history_bars)})

    for tier in tiers:
        while True:
            if args.max_batches and batches >= args.max_batches:
                with db.connect(args.dsn) as conn:
                    log_line({"event": "max_batches_reached", "counts": tier_counts(conn, args.min_history_bars), "batches": batches, "failures": failures})
                return 2 if failures else 0
            if deadline and time.monotonic() >= deadline:
                with db.connect(args.dsn) as conn:
                    log_line({"event": "deadline_reached", "counts": tier_counts(conn, args.min_history_bars), "batches": batches, "failures": failures})
                return 2 if failures else 0
            with db.connect(args.dsn) as conn:
                tickers = remaining_tickers(
                    conn,
                    tier,
                    args.batch_size,
                    args.min_history_bars,
                    exclude=sorted(attempted_this_run),
                )
            if not tickers:
                with db.connect(args.dsn) as conn:
                    log_line({"event": "tier_complete", "tier": tier, "counts": tier_counts(conn, args.min_history_bars)})
                break
            batches += 1
            attempted_this_run.update(tickers)
            log_line({"event": "batch_start", "batch": batches, "tier": tier, "tickers": tickers})
            try:
                result = massive_ingest(
                    tickers=tickers,
                    days=args.days,
                    dsn=args.dsn,
                    min_dollar_vol=Decimal(args.min_dollar_vol),
                    refresh_universe=False,
                    validate=False,
                    adjusted=not args.raw,
                    pause_seconds=args.pause_seconds,
                    min_history_bars=args.min_history_bars,
                    eodhs_fallback_max_tickers=0,
                )
                latest = result.get("latest") or []
                loaded = sum(1 for row in latest if int(row.get("bars") or 0) >= args.min_history_bars)
                log_line({
                    "event": "batch_done",
                    "batch": batches,
                    "tier": tier,
                    "tickers": tickers,
                    "bars_fetched": result.get("bars_fetched"),
                    "ingest_run_id": result.get("ingest_run_id"),
                    "feature_run_id": result.get("feature_run_id"),
                    "loaded_ge_min_history": loaded,
                })
            except Exception as exc:  # keep remaining batches resumable
                failures += 1
                log_line({"event": "batch_error", "batch": batches, "tier": tier, "tickers": tickers, "error": repr(exc)})
                if failures >= args.max_failures:
                    with db.connect(args.dsn) as conn:
                        log_line({"event": "too_many_failures", "counts": tier_counts(conn, args.min_history_bars), "batches": batches, "failures": failures})
                    return 1
                time.sleep(args.error_sleep_seconds)
            if args.batch_sleep_seconds:
                time.sleep(args.batch_sleep_seconds)

    with db.connect(args.dsn) as conn:
        log_line({"event": "complete", "counts": tier_counts(conn, args.min_history_bars), "batches": batches, "failures": failures})
    return 2 if failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resumable Wolfy tiered EOD backfill runner")
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    parser.add_argument("--tiers", nargs="*", default=DEFAULT_TIERS)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--days", type=int, default=730)
    parser.add_argument("--min-history-bars", type=int, default=DEFAULT_MIN_HISTORY_BARS)
    parser.add_argument("--min-dollar-vol", default="25000000")
    parser.add_argument("--pause-seconds", type=float, default=0.25)
    parser.add_argument("--batch-sleep-seconds", type=float, default=1.0)
    parser.add_argument("--error-sleep-seconds", type=float, default=60.0)
    parser.add_argument("--max-failures", type=int, default=5)
    parser.add_argument("--max-runtime-seconds", type=int, default=0, help="0 means no script deadline")
    parser.add_argument("--max-batches", type=int, default=0, help="0 means no batch-count limit")
    parser.add_argument("--raw", action="store_true")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
