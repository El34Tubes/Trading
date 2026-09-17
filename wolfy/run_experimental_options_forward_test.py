#!/usr/bin/env python3
"""Run deterministic experimental options research from read-only chain JSON."""
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from experimental_options_pipeline import PROFILE_STRATEGIES, evaluate_and_write_experimental_options
from options_research_ledger import DEFAULT_DSN
from option_chain_provider import acquire_option_chain_snapshot
from options_structure_selector import (
    strict_aware_datetime,
    strict_mapping,
    strict_mapping_sequence,
)


def load_chain_snapshot(path: Path) -> dict[str, Any]:
    payload = strict_mapping(json.loads(path.read_text()), field="snapshot")
    chains_payload = strict_mapping(payload.get("chains"), field="snapshot chains")
    fetched_at = strict_aware_datetime(payload.get("fetched_at"), field="fetched_at")
    chains: dict[str, list[Mapping[str, Any]]] = {}
    for ticker, contracts in chains_payload.items():
        contracts = strict_mapping_sequence(contracts, field="each chains value")
        chains[str(ticker).upper()] = list(contracts)
    return {
        "fetched_at": fetched_at,
        "source": str(payload.get("source") or "normalized-read-only-chain-json"),
        "chains": chains,
    }


def fetch_cboe_snapshots(
    tickers: list[str], *, signal_dt: date, decision_at: datetime
) -> dict[str, Any]:
    chains: dict[str, Any] = {}
    fetched_times: list[datetime] = []
    for ticker in sorted({ticker.upper().strip() for ticker in tickers if ticker.strip()}):
        snapshot = acquire_option_chain_snapshot(
            ticker, signal_dt=signal_dt, decision_at=decision_at
        )
        chains[ticker] = snapshot
        fetched_times.append(snapshot.fetched_at)
    return {
        "fetched_at": max(fetched_times) if fetched_times else decision_at,
        "source": "cboe_public_delayed_options",
        "chains": chains,
    }


def _aware_datetime(value: str) -> datetime:
    try:
        return strict_aware_datetime(value, field="decision time")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("decision time must include a timezone") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal-dt", type=date.fromisoformat, required=True)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--chain-json", type=Path)
    source_group.add_argument("--cboe-delayed", action="store_true", help="Fetch free public delayed Cboe chains for qualifying signals only")
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--profile", choices=tuple(PROFILE_STRATEGIES), default="v1")
    parser.add_argument("--decision-time", type=_aware_datetime)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    import psycopg
    with psycopg.connect(args.dsn) as conn:
        if args.cboe_delayed:
            decision_at = args.decision_time or datetime.now(timezone.utc)
            qualifying = conn.execute("""
                SELECT DISTINCT s.ticker FROM signals s JOIN strategies st ON st.id=s.strategy_id
                WHERE s.dt=%s AND st.name=%s
                  AND lower(coalesce(s.direction,'')) IN ('long','buy') ORDER BY s.ticker
            """, (args.signal_dt, PROFILE_STRATEGIES[args.profile])).fetchall()
            snapshot = fetch_cboe_snapshots(
                [str(row[0]) for row in qualifying],
                signal_dt=args.signal_dt,
                decision_at=decision_at,
            )
        else:
            snapshot = load_chain_snapshot(args.chain_json)
            decision_at = args.decision_time or snapshot["fetched_at"]
        result = evaluate_and_write_experimental_options(
            conn, signal_dt=args.signal_dt, chain_snapshots=snapshot["chains"],
            fetched_at=snapshot["fetched_at"], source=snapshot["source"], dry_run=args.dry_run,
            profile=args.profile, decision_time=decision_at,
        )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
