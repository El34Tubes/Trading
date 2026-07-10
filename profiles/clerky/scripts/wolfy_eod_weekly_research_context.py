#!/usr/bin/env python3
"""Context script for weekly Wolfy EOD research/backtest review."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo
import datetime as dt

WOLFY_DIR = Path('/root/.hermes/wolfy')
sys.path.insert(0, str(WOLFY_DIR))
from eod_governance import print_eod_governance  # noqa: E402
from budget_wake_gate import budget_wake_gate  # noqa: E402

DSN = 'dbname=wolfy user=root host=/var/run/postgresql'
NY = ZoneInfo('America/New_York')


def main() -> int:
    if not budget_wake_gate(label='Weekly EOD research'):
        return 0
    import psycopg
    print_eod_governance()
    print('WEEKLY_EOD_RESEARCH_CONTEXT')
    print(f'now_et={dt.datetime.now(NY).isoformat()}')
    with psycopg.connect(DSN) as conn:
        strategies = conn.execute("SELECT id,name,status,latest_oos_sharpe,latest_oos_verdict,last_validated,notes FROM strategies ORDER BY id").fetchall()
        print('strategies=' + json.dumps([
            {'id': r[0], 'name': r[1], 'status': r[2], 'latest_oos_sharpe': str(r[3]), 'latest_oos_verdict': r[4], 'last_validated': str(r[5]), 'notes': r[6]} for r in strategies
        ], sort_keys=True, default=str))
        backtests = conn.execute("""
            SELECT b.id, st.name, b.run_at, b.window_start, b.window_end, b.oos_sharpe, b.max_dd, b.survives_oos
            FROM backtests b JOIN strategies st ON st.id=b.strategy_id
            ORDER BY b.run_at DESC LIMIT 10
        """).fetchall()
        print('recent_backtests=' + json.dumps([
            {'id': r[0], 'strategy': r[1], 'run_at': str(r[2]), 'window_start': str(r[3]), 'window_end': str(r[4]), 'oos_sharpe': str(r[5]), 'max_dd': str(r[6]), 'survives_oos': r[7]} for r in backtests
        ], sort_keys=True, default=str))
        log = conn.execute("SELECT ts,hypothesis,outcome,promoted FROM research_log ORDER BY ts DESC LIMIT 10").fetchall()
        print('recent_research_log=' + json.dumps([
            {'ts': str(r[0]), 'hypothesis': r[1], 'outcome': r[2], 'promoted': r[3]} for r in log
        ], sort_keys=True, default=str))
    print('Instruction: summarize weekly EOD research progress, gaps, and next deterministic backtest/research tasks. Do not recommend trades. Strategy approval remains human-gated.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
