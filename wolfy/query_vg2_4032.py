#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres
conn=connect_postgres()
try:
  with conn.cursor() as cur:
    queries={
      'RUN_SUMMARY':("SELECT count(*) n, bool_or(ticker='SPY') spy, bool_or(ticker='QQQ') qqq, array_agg(ticker ORDER BY score DESC) tickers FROM scanner_results WHERE run_id=458",()),
      'SIGNALS':("SELECT * FROM signals WHERE ticker='VG' LIMIT 10",()),
      'SETUPS':("SELECT * FROM setups WHERE ticker='VG' LIMIT 10",()),
      'RULES':("SELECT id,rule_name,rule_type,status,description,parameters FROM strategy_rules WHERE status='approved' ORDER BY id",()),
      'ARTIFACTS':("SELECT id,title,source_fingerprint,created_at FROM agent_artifacts WHERE 'VG'=ANY(ticker_symbols) ORDER BY created_at DESC LIMIT 10",())}
    for label,(sql,p) in queries.items():
      try:
        cur.execute(sql,p); cols=[d.name for d in cur.description]
        print(label,json.dumps([dict(zip(cols,r)) for r in cur.fetchall()],default=str,indent=2))
      except Exception as e:
        print(label,'ERROR',e); conn.rollback()
finally: conn.close()
