#!/usr/bin/env python3
"""Compatibility wrapper for Wolfy's stale agent-coordination cleanup."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name('cleanup_stale_agent_coordination.py')

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, str(SCRIPT), *sys.argv[1:]]))
