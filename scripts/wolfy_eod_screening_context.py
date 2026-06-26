#!/usr/bin/env python3
"""Context script for Wolfy's user-facing EOD screening notification."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo
import datetime as dt

WOLFY_DIR = Path('/root/.hermes/wolfy')
sys.path.insert(0, str(WOLFY_DIR))

from eod_governance import print_eod_governance  # noqa: E402

DSN = 'dbname=wolfy user=root host=/var/run/postgresql'
NY = ZoneInfo('America/New_York')


def main() -> int:
    import psycopg
    print_eod_governance()
    now = dt.datetime.now(NY)
    print('EOD_SCREENING_CONTEXT')
    print(f'now_et={now.isoformat()}')
    with psycopg.connect(DSN) as conn:
        latest = conn.execute('SELECT max(dt) FROM prices').fetchone()[0]
        print(f'latest_price_dt={latest}')
        run_rows = conn.execute("""
            SELECT job, started, finished, status, detail
            FROM runs
            WHERE job IN ('eod_price_ingest','eod_feature_compute')
            ORDER BY started DESC
            LIMIT 6
        """).fetchall()
        print('recent_eod_runs=' + json.dumps([
            {'job': r[0], 'started': str(r[1]), 'finished': str(r[2]), 'status': r[3], 'detail': r[4]} for r in run_rows
        ], sort_keys=True, default=str))
        sig_rows = conn.execute("""
            SELECT s.dt, st.name, st.status, count(*)
            FROM signals s JOIN strategies st ON st.id=s.strategy_id
            WHERE s.dt = (SELECT max(dt) FROM signals)
            GROUP BY s.dt, st.name, st.status
            ORDER BY st.name
        """).fetchall()
        print('latest_signal_counts=' + json.dumps([
            {'dt': str(r[0]), 'strategy': r[1], 'strategy_status': r[2], 'count': int(r[3])} for r in sig_rows
        ], sort_keys=True))
        setup_rows = conn.execute("""
            SELECT for_session, status, count(*), coalesce(string_agg(ticker, ',' ORDER BY rank, ticker), '')
            FROM setups
            WHERE for_session >= current_date - interval '3 days'
            GROUP BY for_session, status
            ORDER BY for_session DESC, status
        """).fetchall()
        print('recent_setups=' + json.dumps([
            {'for_session': str(r[0]), 'status': r[1], 'count': int(r[2]), 'tickers': r[3]} for r in setup_rows
        ], sort_keys=True))
        strategies = conn.execute("SELECT name,status,latest_oos_sharpe,latest_oos_verdict,last_validated FROM strategies ORDER BY name").fetchall()
        print('strategy_gate=' + json.dumps([
            {'name': r[0], 'status': r[1], 'latest_oos_sharpe': str(r[2]), 'latest_oos_verdict': r[3], 'last_validated': str(r[4])} for r in strategies
        ], sort_keys=True, default=str))
    print('Instruction: write a concise Wolfy EOD screening notification. If no approved-gated pending_review setup exists, say NO SETUP / WATCHLIST ONLY and explain the gate. Separate FACT from JUDGMENT. No live trading or intraday action language.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
