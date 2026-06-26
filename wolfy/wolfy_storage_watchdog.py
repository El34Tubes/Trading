#!/usr/bin/env python3
"""Silent watchdog: records Wolfy storage stats to Postgres and prints only threshold alerts."""
from __future__ import annotations
import os, shutil
from pathlib import Path

import psycopg

BASE = Path('/root/.hermes/wolfy')
HERMES = Path('/root/.hermes')
PG_DSN = 'dbname=wolfy user=root host=/var/run/postgresql'
LEGACY_DB = BASE / 'wolfy.db'


def size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
    return total


def human(n: int) -> str:
    value = float(n)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if value < 1024:
            return f'{value:.1f}{unit}'
        value /= 1024
    return f'{value:.1f}PB'


def record_metric(hermes: int, wolfy: int, legacy_db: int, used_pct: float, free_bytes: int) -> None:
    with psycopg.connect(PG_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS system_metrics (
              id BIGSERIAL PRIMARY KEY,
              captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              hermes_bytes BIGINT,
              wolfy_bytes BIGINT,
              legacy_sqlite_bytes BIGINT,
              root_used_pct DOUBLE PRECISION,
              root_avail_bytes BIGINT,
              cron_job_count INTEGER,
              notes TEXT
            )
            """
        )
        cur.execute(
            """
            INSERT INTO system_metrics(hermes_bytes,wolfy_bytes,legacy_sqlite_bytes,root_used_pct,root_avail_bytes,cron_job_count,notes)
            VALUES(%s,%s,%s,%s,%s,%s,%s)
            """,
            (hermes, wolfy, legacy_db, used_pct, free_bytes, None, 'silent Postgres watchdog'),
        )
        conn.commit()


def main() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage('/')
    hermes = size(HERMES)
    wolfy = size(BASE)
    legacy_db = size(LEGACY_DB)
    used = (usage.used / usage.total) * 100
    record_metric(hermes, wolfy, legacy_db, used, usage.free)
    alerts = []
    if used > 70:
        alerts.append(f'Root disk high: {used:.1f}% used, {human(usage.free)} free')
    if wolfy > 20_000_000_000:
        alerts.append(f'Wolfy dir exceeded 20GB: {human(wolfy)} — move artifacts/object storage')
    if alerts:
        print('Wolfy storage alert:\n' + '\n'.join('- ' + a for a in alerts))


if __name__ == '__main__':
    main()
