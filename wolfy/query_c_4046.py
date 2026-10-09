#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres
conn=connect_postgres()
try:
  with conn.cursor() as cur:
    def dump(label,sql,p=()):
      cur.execute(sql,p); cols=[d.name for d in cur.description]
      print(label,json.dumps([dict(zip(cols,r)) for r in cur.fetchall()],default=str,indent=2))
    dump('LEAD',"SELECT * FROM alpha_search_leads WHERE ticker='C' AND scanner_run_id=469 ORDER BY id DESC")
    dump('SCANNER',"SELECT * FROM scanner_results WHERE ticker='C' AND run_id=469 ORDER BY id DESC")
    dump('RUN_ROWS',"SELECT ticker,score,r5,r20,r60,avg_volume,notes FROM scanner_results WHERE run_id=469 ORDER BY score DESC")
    dump('SIGNALS',"SELECT * FROM signals WHERE ticker='C' LIMIT 10")
    dump('SETUPS',"SELECT * FROM setups WHERE ticker='C' LIMIT 10")
    dump('RULES',"SELECT * FROM strategy_rules WHERE status='approved'")
    dump('ARTIFACTS',"SELECT id,title,body,source_url,source_fingerprint,created_at FROM agent_artifacts WHERE 'C'=ANY(ticker_symbols) ORDER BY id DESC LIMIT 20")
finally: conn.close()
