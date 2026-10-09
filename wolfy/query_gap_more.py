#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres
conn=connect_postgres()
try:
  with conn.cursor() as cur:
    checks=[
      ("RUN", "SELECT ticker,close,r20,notes FROM scanner_results WHERE run_id=478 ORDER BY id"),
      ("SIGNALS", "SELECT * FROM signals WHERE ticker='GAP' ORDER BY dt DESC LIMIT 10"),
      ("SETUPS", "SELECT * FROM setups WHERE ticker='GAP' ORDER BY id DESC LIMIT 10"),
      ("ARTIFACTS", "SELECT id,title,source_fingerprint FROM agent_artifacts WHERE 'GAP'=ANY(ticker_symbols) ORDER BY id DESC LIMIT 10")]
    for name,q in checks:
      cur.execute(q); rows=cur.fetchall(); cols=[d.name for d in cur.description]
      print(name+':',json.dumps([dict(zip(cols,r)) for r in rows],default=str,indent=2))
finally: conn.close()
