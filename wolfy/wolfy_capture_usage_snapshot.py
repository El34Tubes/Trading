#!/usr/bin/env python3
"""Compatibility wrapper for Wolfy's aggregate usage snapshot helper."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name('capture_usage_snapshot.py')

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, str(SCRIPT), *sys.argv[1:]]))
