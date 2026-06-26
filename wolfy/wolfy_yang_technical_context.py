#!/usr/bin/env python3
"""Compatibility wrapper for Yang's post-Sentinel technical context.

Older diagnostics may still call wolfy_yang_technical_context.py directly;
the live implementation is yang_technical_context.py.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name('yang_technical_context.py')

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, str(SCRIPT), *sys.argv[1:]]))
