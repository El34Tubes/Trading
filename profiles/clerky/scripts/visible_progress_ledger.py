#!/usr/bin/env python3
"""Compatibility wrapper for Wolfy's read-only visible progress ledger."""
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/wolfy/visible_progress_ledger.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, *sys.argv[1:]]))
