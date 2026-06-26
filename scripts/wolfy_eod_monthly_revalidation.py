#!/usr/bin/env python3
"""Silent no-agent monthly EOD strategy revalidation.

Intended cron: first Monday each month. Prints only when a strategy is demoted
or when invoked with --dry-run.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

WOLFY_DIR = Path('/root/.hermes/wolfy')
sys.path.insert(0, str(WOLFY_DIR))

DSN = 'dbname=wolfy user=root host=/var/run/postgresql'


def main() -> int:
    parser = argparse.ArgumentParser(description='Wolfy EOD monthly strategy revalidation')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--as-of', default=None)
    args = parser.parse_args()
    today = dt.date.fromisoformat(args.as_of) if args.as_of else dt.date.today()
    if not args.dry_run and not (today.weekday() == 0 and today.day <= 7):
        return 0

    import psycopg
    from eod_monitoring import ensure_monitoring_schema, run_monthly_strategy_revalidation

    with psycopg.connect(DSN) as conn:
        ensure_monitoring_schema(conn)
        if args.dry_run:
            rows = conn.execute("""
                SELECT id, name, latest_oos_verdict, last_validated
                FROM strategies
                WHERE status='approved'
                  AND (last_validated IS NULL OR last_validated < %s OR coalesce(latest_oos_verdict, false)=false)
                ORDER BY id
            """, (today - dt.timedelta(days=31),)).fetchall()
            print(json.dumps({'dry_run': True, 'writes': False, 'as_of': str(today), 'would_demote': [dict(id=r[0], name=r[1], latest_oos_verdict=r[2], last_validated=str(r[3])) for r in rows]}, sort_keys=True, default=str))
            return 0
        result = run_monthly_strategy_revalidation(conn, as_of=today)
    if result.get('strategies_demoted'):
        print(json.dumps(result, sort_keys=True, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
