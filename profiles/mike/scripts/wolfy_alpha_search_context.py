#!/usr/bin/env python3
"""Compatibility wrapper for Wolfy's standalone Alpha Search context."""
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/wolfy/alpha_search_context.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, *sys.argv[1:]]))
