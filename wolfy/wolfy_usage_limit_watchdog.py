#!/usr/bin/env python3
"""Compatibility wrapper for Wolfy's usage-limit watchdog."""
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/scripts/wolfy_usage_limit_watchdog.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, *sys.argv[1:]]))
