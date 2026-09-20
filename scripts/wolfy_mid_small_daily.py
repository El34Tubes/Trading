#!/usr/bin/env python3
"""Safe entrypoint for the mid/small-cap orchestrator.

The command remains shadow-only by default. Task 23 canary authorization is an
explicit in-process gate and never enables or creates a scheduled publisher.
"""
from __future__ import annotations

from pathlib import Path
import sys

WOLFY_DIR = Path(__file__).resolve().parents[1] / "wolfy"
if str(WOLFY_DIR) not in sys.path:
    sys.path.insert(0, str(WOLFY_DIR))

from orchestration_runner import main_mid_small_shadow  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main_mid_small_shadow())
