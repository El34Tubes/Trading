#!/usr/bin/env python3
"""Compatibility wrapper for Sentinel's post-Wolfy review context."""
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/wolfy/sentinel_review_context.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, *sys.argv[1:]]))
