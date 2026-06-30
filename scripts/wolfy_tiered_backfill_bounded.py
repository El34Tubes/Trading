#!/usr/bin/env python3
"""Wolfy bounded tiered EOD history backfill loop.

Script-only cron wrapper. Loads a few active/enabled large/mid/small-cap tickers
per run using Massive adjusted daily bars. Bounded to fit Hermes cron's script
window and resume safely next tick.
"""
from __future__ import annotations

import subprocess
import sys

CMD = [
    sys.executable,
    "/root/.hermes/wolfy/backfill_tiered_remaining.py",
    "--tiers", "large_cap", "mid_cap", "small_cap",
    "--batch-size", "2",
    "--days", "730",
    "--min-history-bars", "495",
    "--pause-seconds", "0",
    "--batch-sleep-seconds", "0",
    "--max-runtime-seconds", "90",
    "--max-batches", "4",
    "--max-failures", "1",
]

if __name__ == "__main__":
    raise SystemExit(subprocess.call(CMD))
