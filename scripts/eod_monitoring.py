#!/usr/bin/env python3
"""Compatibility wrapper for Wolfy's EOD monitoring/revalidation helper."""
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/wolfy/eod_monitoring.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, *sys.argv[1:]]))
