#!/usr/bin/env python3
"""Compatibility wrapper for Wolfy's Postgres coordination CLI.

The canonical implementation and its local imports live in the Wolfy directory;
cron planners and profile-scoped diagnostics may call this stable scripts path.
"""
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/wolfy/wolfy_agent_cli.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, *sys.argv[1:]]))
