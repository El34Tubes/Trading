#!/usr/bin/env python3
"""Silent watchdog: records Wolfy storage stats and prints only threshold alerts."""
from __future__ import annotations
import os, sqlite3, shutil
from pathlib import Path
BASE=Path('/root/.hermes/wolfy'); DB=BASE/'wolfy.db'; HERMES=Path('/root/.hermes')
def size(path: Path)->int:
    if not path.exists(): return 0
    if path.is_file(): return path.stat().st_size
    total=0
    for root, dirs, files in os.walk(path):
        for f in files:
            try: total+=(Path(root)/f).stat().st_size
            except OSError: pass
    return total
def human(n:int)->str:
    for u in ['B','KB','MB','GB','TB']:
        if n<1024: return f'{n:.1f}{u}'
        n/=1024
    return f'{n:.1f}PB'
def main():
    BASE.mkdir(parents=True, exist_ok=True)
    usage=shutil.disk_usage('/')
    hermes=size(HERMES); wolfy=size(BASE); db=size(DB)
    if DB.exists():
        con=sqlite3.connect(DB)
        con.execute("INSERT INTO system_metrics(hermes_bytes,wolfy_bytes,db_bytes,root_used_pct,root_avail_bytes,cron_job_count,notes) VALUES(?,?,?,?,?,?,?)",(hermes,wolfy,db,(usage.used/usage.total)*100,usage.free,None,'silent watchdog'))
        con.commit(); con.close()
    alerts=[]
    used=(usage.used/usage.total)*100
    if used>70: alerts.append(f'Root disk high: {used:.1f}% used, {human(usage.free)} free')
    if db>1_000_000_000: alerts.append(f'Wolfy DB exceeded 1GB: {human(db)} — optimize/archive soon')
    if db>5_000_000_000: alerts.append(f'Wolfy DB exceeded 5GB: {human(db)} — migrate to Postgres')
    if wolfy>20_000_000_000: alerts.append(f'Wolfy dir exceeded 20GB: {human(wolfy)} — move artifacts/object storage')
    if alerts:
        print('Wolfy storage alert:\n' + '\n'.join('- '+a for a in alerts))
if __name__=='__main__': main()
