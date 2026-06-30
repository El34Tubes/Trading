#!/usr/bin/env python3
"""Stable Hermes cron entrypoint for Wolfy EOD Massive ingest shard 2/5."""
from __future__ import annotations

import sys
from pathlib import Path

WOLFY_DIR = Path("/root/.hermes/wolfy")
sys.path.insert(0, str(WOLFY_DIR))

from orchestration_runner import run_eod_ingest_shard


def main() -> int:
    return run_eod_ingest_shard(2)


if __name__ == "__main__":
    raise SystemExit(main())
