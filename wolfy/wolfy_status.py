#!/usr/bin/env python3
"""Capture and print Wolfy DB/storage/cron status."""
from __future__ import annotations
import os, sqlite3, shutil, subprocess
from pathlib import Path

BASE=Path('/root/.hermes/wolfy')
DB=BASE/'wolfy.db'
HERMES=Path('/root/.hermes')

def size(path: Path) -> int:
    if not path.exists(): return 0
    if path.is_file(): return path.stat().st_size
    total=0
    for root, dirs, files in os.walk(path):
        for f in files:
            try: total += (Path(root)/f).stat().st_size
            except OSError: pass
    return total

def human(n:int)->str:
    for unit in ['B','KB','MB','GB','TB']:
        if n < 1024: return f'{n:.1f}{unit}'
        n/=1024
    return f'{n:.1f}PB'

def main():
    BASE.mkdir(parents=True, exist_ok=True)
    usage=shutil.disk_usage('/')
    hermes_bytes=size(HERMES); wolfy_bytes=size(BASE); db_bytes=size(DB)
    cron_count=0
    try:
        out=subprocess.run(['hermes','cron','list'],capture_output=True,text=True,timeout=30).stdout
        cron_count=out.count('Job ID:') or out.count('job_id')
    except Exception:
        pass
    if DB.exists():
        con=sqlite3.connect(DB)
        try:
            con.execute("""INSERT INTO system_metrics(hermes_bytes,wolfy_bytes,db_bytes,root_used_pct,root_avail_bytes,cron_job_count,notes)
                           VALUES(?,?,?,?,?,?,?)""", (hermes_bytes,wolfy_bytes,db_bytes,(usage.used/usage.total)*100,usage.free,cron_count,'automated status capture'))
            con.commit()
            tables=['knowledge_sources','knowledge_notes','strategy_rules','training_tasks','scanner_runs','scanner_results','recommendations','paper_trades','recommendation_outcomes','reports','system_metrics']
            counts={t: con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in tables}
        finally:
            con.close()
    else:
        counts={}
    print('Wolfy Status')
    print(f'DB: {DB} exists={DB.exists()} size={human(db_bytes)}')
    print(f'Wolfy dir: {human(wolfy_bytes)} | Hermes dir: {human(hermes_bytes)}')
    print(f'Root disk: used={(usage.used/usage.total)*100:.1f}% avail={human(usage.free)} total={human(usage.total)}')
    if counts:
        print('Counts: ' + ', '.join(f'{k}={v}' for k,v in counts.items()))
    print('Scale-up thresholds: SQLite OK until ~1-5GB DB or concurrent writer contention; move to Postgres + object storage/vector index if DB >5GB, Hermes dir >20GB, disk >70%, or multiple agents write heavily.')
if __name__=='__main__': main()
