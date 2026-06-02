#!/usr/bin/env python3
"""Compatibility wrapper for Wolfy's standalone Alpha Search context.

Older diagnostics may still call wolfy_alpha_search_context.py directly;
the live implementation is alpha_search_context.py.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name('alpha_search_context.py')

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, str(SCRIPT), *sys.argv[1:]]))
