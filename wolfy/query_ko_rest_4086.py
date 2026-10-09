#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres
conn=connect_postgres()
try:
  with conn.cursor() as cur:
    def q(label,sql):
      cur.execute(sql); cols=[d.name for d in cur.description or []]
      print(label+'='+json.dumps([dict(zip(cols,r)) for r in cur.fetchall()],default=str))
    q('SIGNALS',"SELECT * FROM signals WHERE ticker='KO' ORDER BY dt DESC LIMIT 10")
    q('SETUPS',"SELECT * FROM setups WHERE ticker='KO' ORDER BY created_dt DESC LIMIT 10")
    q('RULES',"SELECT id,name,title,status,implementation_status,description,summary,body,rule_body,metadata,rule_text FROM strategy_rules WHERE status='approved' ORDER BY id")
    q('EXISTING',"SELECT id,title,source_fingerprint,created_at FROM agent_artifacts WHERE 'KO'=ANY(ticker_symbols) ORDER BY id DESC LIMIT 10")
finally: conn.close()
