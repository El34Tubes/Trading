#!/usr/bin/env python3
"""Compatibility wrapper for Wolfy's silent intraday scanner snapshot.

Older diagnostics may still call wolfy_intraday_scanner_snapshot.py directly;
the live implementation is intraday_scanner_snapshot.py.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name('intraday_scanner_snapshot.py')

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, str(SCRIPT), *sys.argv[1:]]))
