#!/usr/bin/env python3
"""Compatibility wrapper for Jonah's hourly/autonomous knowledge context."""
from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path

WOLFY_DIR = Path('/root/.hermes/wolfy')
if str(WOLFY_DIR) not in sys.path:
    sys.path.insert(0, str(WOLFY_DIR))


def budget_allows_wake() -> bool:
    """Return False when the deterministic Wolfy budget gate blocks LLM spend.

    Cron's scheduler skips the agent entirely when the final script-output line is
    JSON with {"wakeAgent": false}; keep the human-readable "skipped: budget"
    line before that machine gate.
    """
    gate = WOLFY_DIR / 'guardian' / 'budget_gate.py'
    proc = subprocess.run(
        [sys.executable, str(gate), '--no-record'],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=45,
        check=False,
    )
    output = (proc.stdout or '').strip()
    if proc.returncode == 0:
        if output:
            print(output)
        return True
    print(f'skipped: budget {output or f"budget_gate_exit={proc.returncode}"}')
    print(json.dumps({'wakeAgent': False, 'reason': 'skipped: budget'}))
    return False


if budget_allows_wake():
    runpy.run_path(str(WOLFY_DIR / 'hourly_knowledge_context.py'), run_name='__main__')
