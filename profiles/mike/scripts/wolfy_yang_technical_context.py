#!/usr/bin/env python3
"""Compatibility wrapper for Yang's post-Sentinel technical context."""
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/wolfy/yang_technical_context.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, *sys.argv[1:]]))
