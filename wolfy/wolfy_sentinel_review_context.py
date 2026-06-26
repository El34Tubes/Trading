#!/usr/bin/env python3
"""Compatibility wrapper for Sentinel's post-Wolfy review context.

Older diagnostics may still call wolfy_sentinel_review_context.py directly;
the live implementation is sentinel_review_context.py.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name('sentinel_review_context.py')

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, str(SCRIPT), *sys.argv[1:]]))
