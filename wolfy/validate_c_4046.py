#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres
conn=connect_postgres()
try:
  with conn.cursor() as cur:
    cur.execute("SELECT count(*), count(*) FILTER (WHERE ticker IN ('SPY','QQQ')), bool_and((notes->>'rs_spy_20')::numeric=r20), bool_and((notes->>'rs_qqq_20')::numeric=r20) FROM scanner_results WHERE run_id=469")
    print('RUN_CHECK',cur.fetchone())
    for table in ['prices','features']:
      cur.execute(f"SELECT * FROM {table} WHERE ticker='C' AND dt='2026-09-04'")
      cols=[d.name for d in cur.description]
      print(table,json.dumps([dict(zip(cols,r)) for r in cur.fetchall()],default=str,indent=2))
    cur.execute("SELECT count(*) FROM signals WHERE ticker='C' AND dt='2026-09-04'")
    print('SIGNAL_COUNT',cur.fetchone()[0])
    cur.execute("SELECT count(*) FROM setups WHERE ticker='C'")
    print('SETUP_COUNT',cur.fetchone()[0])
finally: conn.close()
