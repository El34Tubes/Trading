#!/usr/bin/env python3
"""Wolfy EOD after-close price ingest + feature wrapper.

Normal mode writes idempotent Yahoo delayed daily bars and deterministic features to
Postgres. --dry-run fetches/compute-checks a tiny universe in memory only.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

WOLFY_DIR = Path('/root/.hermes/wolfy')
sys.path.insert(0, str(WOLFY_DIR))

CORE_UNIVERSE = 'SPY,QQQ,IWM,DIA,XLK,XLF,XLY,XLI,XLE,XLV,XLP,XLU,XLB,XLRE,XLC,AAPL,MSFT,NVDA,AMZN,GOOGL,META,TSLA,AVGO,JPM,LLY,V,UNH,COST,NFLX,AMD,ORCL,CRM,PANW,SMH'
DRY_UNIVERSE = 'SPY,QQQ,IWM'


def main() -> int:
    parser = argparse.ArgumentParser(description='Wolfy EOD after-close ingest/features wrapper')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--tickers', default=None)
    parser.add_argument('--days', type=int, default=730)
    args = parser.parse_args()

    tickers_csv = args.tickers or (DRY_UNIVERSE if args.dry_run else CORE_UNIVERSE)
    tickers = [t.strip().upper() for t in tickers_csv.split(',') if t.strip()]

    if args.dry_run:
        from eod_price_features import fetch_yahoo_chart_bars, compute_feature_rows
        bars = fetch_yahoo_chart_bars(tickers, days=min(args.days, 30))
        rows = compute_feature_rows(bars)
        print(json.dumps({
            'dry_run': True,
            'writes': False,
            'tickers': tickers,
            'bars_fetched': len(bars),
            'feature_rows_computed': len(rows),
            'latest_dates': {t: max((str(b.dt) for b in bars if b.ticker == t), default=None) for t in tickers},
        }, sort_keys=True))
        return 0

    cmd = [sys.executable, str(WOLFY_DIR / 'eod_price_features.py'), '--tickers', ','.join(tickers), '--days', str(args.days)]
    return subprocess.call(cmd)


if __name__ == '__main__':
    raise SystemExit(main())
