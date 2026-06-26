#!/usr/bin/env python3
"""Wolfy EOD deterministic signals + approved-gated setup writer.

Normal mode writes deterministic signals and pending_review setups only for already
approved strategies. --dry-run reads the latest price date and exercises the
approved setup gate with dry_run=True without creating rows.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

WOLFY_DIR = Path('/root/.hermes/wolfy')
sys.path.insert(0, str(WOLFY_DIR))

CORE_UNIVERSE = 'SPY,QQQ,IWM,DIA,XLK,XLF,XLY,XLI,XLE,XLV,XLP,XLU,XLB,XLRE,XLC,AAPL,MSFT,NVDA,AMZN,GOOGL,META,TSLA,AVGO,JPM,LLY,V,UNH,COST,NFLX,AMD,ORCL,CRM,PANW,SMH'


def _next_business_day(day: dt.date) -> dt.date:
    day = day + dt.timedelta(days=1)
    while day.weekday() >= 5:
        day += dt.timedelta(days=1)
    return day


def _latest_price_date(conn, tickers: list[str]) -> dt.date:
    row = conn.execute('SELECT max(dt) FROM prices WHERE ticker = ANY(%s)', (tickers,)).fetchone()
    if not row or row[0] is None:
        raise RuntimeError('no EOD prices available for signal generation')
    return row[0]


def main() -> int:
    parser = argparse.ArgumentParser(description='Wolfy EOD features/signals/setup wrapper')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--tickers', default=CORE_UNIVERSE)
    parser.add_argument('--signal-dt', default=None)
    args = parser.parse_args()
    tickers = [t.strip().upper() for t in args.tickers.split(',') if t.strip()]

    import psycopg
    from eod_signals import propose_approved_setups

    with psycopg.connect('dbname=wolfy user=root host=/var/run/postgresql') as conn:
        signal_dt = dt.date.fromisoformat(args.signal_dt) if args.signal_dt else _latest_price_date(conn, tickers)
        for_session = _next_business_day(signal_dt)
        if args.dry_run:
            gate = propose_approved_setups(conn, signal_dt=signal_dt, for_session=for_session, tickers=tickers, dry_run=True)
            print(json.dumps({'dry_run': True, 'writes': False, 'signal_dt': str(signal_dt), 'for_session': str(for_session), 'approved_gate': gate}, sort_keys=True, default=str))
            return 0

    cmd = [sys.executable, str(WOLFY_DIR / 'eod_signals.py'), '--tickers', ','.join(tickers), '--signal-dt', str(signal_dt), '--for-session', str(for_session), '--create-setups']
    return subprocess.call(cmd)


if __name__ == '__main__':
    raise SystemExit(main())
