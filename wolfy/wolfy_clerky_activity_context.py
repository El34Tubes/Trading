#!/usr/bin/env python3
"""Compatibility wrapper for Clerky's deterministic activity context."""
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/scripts/wolfy_clerky_activity_context.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, *sys.argv[1:]]))
