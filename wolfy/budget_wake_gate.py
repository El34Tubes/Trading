#!/usr/bin/env python3
"""Shared budget wake-gate helper for Wolfy LLM cron context scripts."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

BUDGET_GATE = Path('/root/.hermes/wolfy/guardian/budget_gate.py')


def budget_wake_gate(*, label: str = 'Wolfy') -> bool:
    """Return False after emitting cron wakeAgent=false JSON when budget blocks.

    The final non-empty stdout line must be JSON so Hermes cron skips the LLM
    call instead of spending tokens after a deterministic context script.
    """
    if os.environ.get('WOLFY_SKIP_BUDGET_GATE') == '1':
        return True
    if not BUDGET_GATE.exists():
        print(f'Budget gate: missing; {label} blocked, do not spend LLM tokens.')
        print('{"wakeAgent": false, "reason": "budget_gate_missing"}')
        return False
    try:
        proc = subprocess.run(
            ['python3', str(BUDGET_GATE), '--no-record'],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
            check=False,
        )
    except Exception as exc:
        print(f'Budget gate: error {type(exc).__name__}: {exc}; {label} blocked, do not spend LLM tokens.')
        print('{"wakeAgent": false, "reason": "budget_gate_error"}')
        return False
    gate_output = ' '.join((proc.stdout or '').split())
    if proc.returncode == 0 and gate_output.startswith('BUDGET=ok'):
        print(f'Budget gate: {gate_output}')
        return True
    reason = gate_output or f'exit={proc.returncode}'
    print(f'skipped: budget {reason}')
    print('{"wakeAgent": false, "reason": "budget"}')
    return False
