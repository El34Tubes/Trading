#!/usr/bin/env python3
"""Wolfy EOD after-close price ingest + feature wrapper.

Stable Hermes cron entrypoint. Shared orchestration lives in
/root/.hermes/wolfy/orchestration_config.py and orchestration_runner.py.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

WOLFY_DIR = Path("/root/.hermes/wolfy")
sys.path.insert(0, str(WOLFY_DIR))

from orchestration_config import CORE_EOD_UNIVERSE, DEFAULT_EOD_LOOKBACK_DAYS, DEFAULT_EOD_SOURCE, DRY_RUN_EOD_UNIVERSE, tickers_csv
from orchestration_runner import run_eod_ingest


def main() -> int:
    parser = argparse.ArgumentParser(description="Wolfy EOD after-close ingest/features wrapper")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--tickers", default=None)
    parser.add_argument("--days", type=int, default=DEFAULT_EOD_LOOKBACK_DAYS)
    parser.add_argument("--source", choices=["massive", "eodhs", "yahoo"], default=DEFAULT_EOD_SOURCE)
    parser.add_argument("--refresh-universe", action="store_true")
    parser.add_argument(
        "--eodhs-fallback-max-tickers",
        type=int,
        default=0,
        help="Conservative EODHS fallback cap for Massive missing-ticker retries; 0 disables",
    )
    args = parser.parse_args()

    default_universe = DRY_RUN_EOD_UNIVERSE if args.dry_run else CORE_EOD_UNIVERSE
    selected_tickers = [ticker.strip().upper() for ticker in (args.tickers or tickers_csv(default_universe)).split(",") if ticker.strip()]
    return run_eod_ingest(
        tickers=selected_tickers,
        source=args.source,
        days=args.days,
        dry_run=args.dry_run,
        refresh_universe=args.refresh_universe,
        eodhs_fallback_max_tickers=args.eodhs_fallback_max_tickers,
    )


if __name__ == "__main__":
    raise SystemExit(main())
