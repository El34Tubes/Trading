#!/usr/bin/env python3
"""Wolfy bounded tiered EOD history backfill loop.

Script-only cron wrapper. Loads a few active/enabled large/mid/small-cap tickers
per run using Massive adjusted daily bars. Bounded to fit Hermes cron's script
window and resume safely next tick.
"""
from __future__ import annotations

import subprocess
import sys


def python_cmd() -> list[str]:
    """Return an interpreter with psycopg available for the Postgres backfill."""
    try:
        import psycopg  # noqa: F401
    except ModuleNotFoundError:
        return ["uvx", "--with", "psycopg[binary]", "python"]
    return [sys.executable]


CMD = [
    *python_cmd(),
    "/root/.hermes/wolfy/backfill_tiered_remaining.py",
    "--tiers", "large_cap", "mid_cap", "small_cap",
    "--batch-size", "2",
    "--days", "730",
    "--min-history-bars", "495",
    "--pause-seconds", "0",
    "--batch-sleep-seconds", "0",
    "--max-runtime-seconds", "75",
    "--max-batches", "2",
    "--max-failures", "1",
]

if __name__ == "__main__":
    # Preserve cron's bounded defaults, but pass through explicit operator args
    # such as --help/--raw so smoke checks are read-only and don't accidentally
    # launch a live backfill run.
    raise SystemExit(subprocess.call(CMD + sys.argv[1:]))
