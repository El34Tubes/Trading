#!/usr/bin/env python3
"""Wait for a tiered backfill process, then run Wolfy signal/update verification."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import psycopg
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit("psycopg is required; run with: uvx --with 'psycopg[binary]' python post_tiered_backfill_verify.py") from exc

DEFAULT_DSN = os.environ.get("WOLFY_POSTGRES_DSN", "dbname=wolfy user=root host=/var/run/postgresql")
ROOT = Path(__file__).resolve().parent


def log(payload: dict) -> None:
    print(json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **payload}, sort_keys=True), flush=True)


def process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def fetch_counts(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT t.tier,
               count(*) AS targets,
               count(*) FILTER (WHERE coalesce(p.bars,0) >= 500) AS loaded_500,
               count(*) FILTER (WHERE coalesce(p.bars,0) > 0 AND coalesce(p.bars,0) < 500) AS partial,
               count(*) FILTER (WHERE coalesce(p.bars,0) = 0) AS missing
        FROM universe_backfill_targets t
        LEFT JOIN (SELECT ticker, count(*) bars FROM prices GROUP BY ticker) p ON p.ticker=t.symbol
        WHERE t.active
        GROUP BY t.tier
        ORDER BY min(t.priority), t.tier
        """
    ).fetchall()
    return [{"tier": r[0], "targets": int(r[1]), "loaded_500": int(r[2]), "partial": int(r[3]), "missing": int(r[4])} for r in rows]


def loaded_target_tickers(conn) -> list[str]:
    rows = conn.execute(
        """
        SELECT t.symbol
        FROM universe_backfill_targets t
        JOIN (SELECT ticker, count(*) bars FROM prices GROUP BY ticker) p ON p.ticker=t.symbol
        WHERE t.active AND p.bars >= 500
        ORDER BY t.priority, t.symbol
        """
    ).fetchall()
    return [r[0] for r in rows]


def common_signal_dt(conn, tickers: list[str]) -> str | None:
    if not tickers:
        return None
    row = conn.execute(
        """
        WITH latest AS (
          SELECT ticker, max(dt) latest_dt
          FROM features
          WHERE ticker = ANY(%s)
          GROUP BY ticker
        )
        SELECT min(latest_dt)::text FROM latest
        """,
        (tickers,),
    ).fetchone()
    return row[0] if row and row[0] else None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait-pid", type=int, required=True)
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    parser.add_argument("--poll-seconds", type=int, default=60)
    args = parser.parse_args(argv)

    log({"event": "post_wait_start", "wait_pid": args.wait_pid})
    while process_running(args.wait_pid):
        time.sleep(args.poll_seconds)
    log({"event": "backfill_process_exited", "wait_pid": args.wait_pid})

    with psycopg.connect(args.dsn) as conn:
        counts = fetch_counts(conn)
        tickers = loaded_target_tickers(conn)
        signal_dt = common_signal_dt(conn, tickers)
    log({"event": "post_counts", "counts": counts, "loaded_tickers": len(tickers), "common_signal_dt": signal_dt})

    signal_result = None
    if signal_dt and tickers:
        for_session = (datetime.fromisoformat(signal_dt).date() + timedelta(days=1)).isoformat()
        cmd = [sys.executable, str(ROOT / "eod_signals.py"), "--tickers", ",".join(tickers), "--signal-dt", signal_dt, "--for-session", for_session, "--create-setups"]
        proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=600)
        signal_result = {"returncode": proc.returncode, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-2000:]}
        log({"event": "signals_done", "result": signal_result})

    test_proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "test_wolfy_tiered_universe.py", "test_eod_price_features.py", "test_eod_signals.py"], cwd=str(ROOT), text=True, capture_output=True, timeout=600)
    log({"event": "tests_done", "returncode": test_proc.returncode, "stdout": test_proc.stdout[-4000:], "stderr": test_proc.stderr[-2000:]})
    return 0 if (not signal_result or signal_result["returncode"] == 0) and test_proc.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
