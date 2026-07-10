#!/usr/bin/env python3
"""Compatibility wrapper for Wolfy's config guardian.

Profile-scoped Mike cron jobs can inherit HERMES_HOME under the Mike profile,
but this guardian protects the production/default Hermes config and cron files.
Pin --home to /root/.hermes so direct Python probes and the shell wrapper behave
identically.
"""
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/wolfy/guardian/config_guardian.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, '--home', '/root/.hermes', *sys.argv[1:]]))
