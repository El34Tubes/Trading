#!/usr/bin/env python3
"""Wolfy EOD deterministic signals + approved-gated setup writer.

Stable Hermes cron entrypoint. Shared orchestration lives in
/root/.hermes/wolfy/orchestration_config.py and orchestration_runner.py.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

WOLFY_DIR = Path("/root/.hermes/wolfy")
sys.path.insert(0, str(WOLFY_DIR))

from orchestration_config import CORE_EOD_UNIVERSE, tickers_csv
from orchestration_runner import run_eod_features_signals


def main() -> int:
    parser = argparse.ArgumentParser(description="Wolfy EOD features/signals/setup wrapper")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--tickers", default=tickers_csv(CORE_EOD_UNIVERSE))
    parser.add_argument("--signal-dt", default=None)
    args = parser.parse_args()
    return run_eod_features_signals(
        tickers_csv_value=args.tickers,
        signal_dt_value=args.signal_dt,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
