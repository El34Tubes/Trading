#!/usr/bin/env python3
"""Compatibility wrapper for Clerky's bounded Kanban allocator."""
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/scripts/wolfy_kanban_allocator.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, *sys.argv[1:]]))
