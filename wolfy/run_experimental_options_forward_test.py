#!/usr/bin/env python3
"""Run deterministic experimental options research from read-only chain JSON."""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from experimental_options_pipeline import evaluate_and_write_experimental_options
from options_research_ledger import DEFAULT_DSN
from cboe_delayed_options import fetch_cboe_delayed_chain


def load_chain_snapshot(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict) or not isinstance(payload.get("chains"), dict):
        raise ValueError("snapshot must contain a ticker-keyed 'chains' object")
    fetched_at = datetime.fromisoformat(str(payload["fetched_at"]).replace("Z", "+00:00"))
    return {
        "fetched_at": fetched_at,
        "source": str(payload.get("source") or "normalized-read-only-chain-json"),
        "chains": {str(ticker).upper(): contracts for ticker, contracts in payload["chains"].items()},
    }


def fetch_cboe_snapshots(tickers: list[str]) -> dict[str, Any]:
    chains: dict[str, Any] = {}
    fetched_times: list[datetime] = []
    for ticker in sorted({ticker.upper().strip() for ticker in tickers if ticker.strip()}):
        snapshot = fetch_cboe_delayed_chain(ticker)
        chains[ticker] = snapshot["contracts"]
        fetched_times.append(snapshot["fetched_at"])
    return {
        "fetched_at": max(fetched_times) if fetched_times else datetime.now().astimezone(),
        "source": "cboe_public_delayed_options",
        "chains": chains,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal-dt", type=date.fromisoformat, required=True)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--chain-json", type=Path)
    source_group.add_argument("--cboe-delayed", action="store_true", help="Fetch free public delayed Cboe chains for qualifying signals only")
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    import psycopg
    with psycopg.connect(args.dsn) as conn:
        if args.cboe_delayed:
            qualifying = conn.execute("""
                SELECT DISTINCT s.ticker FROM signals s JOIN strategies st ON st.id=s.strategy_id
                WHERE s.dt=%s AND st.name='liquid_rs_breakout_options_volatility_v1'
                  AND lower(coalesce(s.direction,'')) IN ('long','buy') ORDER BY s.ticker
            """, (args.signal_dt,)).fetchall()
            snapshot = fetch_cboe_snapshots([str(row[0]) for row in qualifying])
        else:
            snapshot = load_chain_snapshot(args.chain_json)
        result = evaluate_and_write_experimental_options(
            conn, signal_dt=args.signal_dt, chain_snapshots=snapshot["chains"],
            fetched_at=snapshot["fetched_at"], source=snapshot["source"], dry_run=args.dry_run,
        )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
