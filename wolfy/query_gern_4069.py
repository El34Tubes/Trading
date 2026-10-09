#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres
conn=connect_postgres()
try:
  with conn.cursor() as cur:
    def dump(label,sql,params=()):
      try:
        cur.execute(sql,params); cols=[d.name for d in cur.description]
        print(label,json.dumps([dict(zip(cols,r)) for r in cur.fetchall()],default=str,indent=2))
      except Exception as exc:
        conn.rollback(); print(label+'_ERROR',repr(exc))
    dump('TASK','SELECT * FROM agent_tasks WHERE id=%s',(4069,))
    dump('LEADS',"SELECT * FROM alpha_search_leads WHERE ticker='GERN' OR title ILIKE '%%GERN%%' ORDER BY id DESC LIMIT 20")
    dump('SCANNER',"SELECT * FROM scanner_results WHERE ticker='GERN' ORDER BY id DESC LIMIT 10")
    dump('RUN_ROWS',"SELECT * FROM scanner_results WHERE run_id=(SELECT run_id FROM scanner_results WHERE ticker='GERN' ORDER BY id DESC LIMIT 1) ORDER BY id")
    dump('FEATURES',"SELECT * FROM features WHERE ticker='GERN' ORDER BY dt DESC LIMIT 5")
    dump('PRICES',"SELECT * FROM prices WHERE ticker='GERN' ORDER BY dt DESC LIMIT 5")
    dump('SIGNALS',"SELECT * FROM signals WHERE ticker='GERN' ORDER BY dt DESC LIMIT 10")
    dump('SETUPS',"SELECT * FROM setups WHERE ticker='GERN' ORDER BY created_dt DESC LIMIT 10")
    dump('APPROVED_RULES',"SELECT * FROM strategy_rules WHERE status='approved' ORDER BY id")
    dump('EXISTING',"SELECT id,title,body,source_url,source_fingerprint,created_at FROM agent_artifacts WHERE 'GERN'=ANY(ticker_symbols) ORDER BY id DESC LIMIT 10")
finally: conn.close()
