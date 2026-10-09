#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres
conn=connect_postgres()
try:
  with conn.cursor() as cur:
    queries={
      'TASK':("SELECT * FROM agent_tasks WHERE id=%s",(4076,)),
      'LEADS':("SELECT * FROM alpha_search_leads WHERE ticker='HYMB' OR title ILIKE '%%HYMB%%' ORDER BY id DESC LIMIT 20",()),
      'SCANNER':("SELECT * FROM scanner_results WHERE ticker='HYMB' ORDER BY id DESC LIMIT 20",()),
      'RUN_ROWS':("SELECT * FROM scanner_results WHERE run_id=(SELECT run_id FROM scanner_results WHERE ticker='HYMB' ORDER BY id DESC LIMIT 1) ORDER BY score DESC",()),
      'FEATURES':("SELECT * FROM features WHERE ticker='HYMB' ORDER BY date DESC LIMIT 5",()),
      'PRICES':("SELECT * FROM prices WHERE ticker='HYMB' ORDER BY date DESC LIMIT 5",()),
      'SIGNALS':("SELECT * FROM signals WHERE ticker='HYMB' ORDER BY created_at DESC LIMIT 10",()),
      'SETUPS':("SELECT * FROM setups WHERE ticker='HYMB' ORDER BY created_at DESC LIMIT 10",()),
      'RULES':("SELECT id,rule_name,rule_type,status,description,parameters FROM strategy_rules WHERE status='approved' ORDER BY id",()),
      'ARTIFACTS':("SELECT id,title,body,source_url,source_fingerprint,created_at FROM agent_artifacts WHERE 'HYMB'=ANY(ticker_symbols) ORDER BY created_at DESC LIMIT 10",())}
    for label,(sql,p) in queries.items():
      try:
        cur.execute(sql,p); cols=[d.name for d in cur.description]
        print(label,json.dumps([dict(zip(cols,r)) for r in cur.fetchall()],default=str,indent=2))
      except Exception as e:
        print(label,'ERROR',e); conn.rollback()
finally: conn.close()
