#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres
conn=connect_postgres()
try:
  with conn.cursor() as cur:
    def q(label,sql,p=()):
      cur.execute(sql,p); cols=[d.name for d in cur.description]; print(label,json.dumps([dict(zip(cols,r)) for r in cur.fetchall()],default=str,indent=2))
    q('RUN_STATS', """SELECT count(*) row_count, bool_or(ticker='SPY') spy_present, bool_or(ticker='QQQ') qqq_present,
      count(*) FILTER (WHERE (notes->>'rs_spy_20')::float=r20) rs_spy_equals_own_r20,
      count(*) FILTER (WHERE (notes->>'rs_qqq_20')::float=r20) rs_qqq_equals_own_r20,
      min(created_at) created_at FROM scanner_results WHERE run_id=479""")
    q('SIGNALS', "SELECT * FROM signals WHERE ticker='GEN' ORDER BY dt DESC LIMIT 10")
    q('SETUPS', "SELECT * FROM setups WHERE ticker='GEN' ORDER BY created_dt DESC LIMIT 10")
    q('RULES', "SELECT id,name,title,status,implementation_status,rule_type,timeframe,setup_type,description,summary,body,rule_body,metadata,source_basis,enabled,is_enabled,is_active,rule_text FROM strategy_rules WHERE status='approved' ORDER BY id")
    q('RESEARCH', "SELECT id,title,source_url,source_fingerprint,created_at FROM agent_artifacts WHERE 'GEN'=ANY(ticker_symbols) ORDER BY id DESC LIMIT 10")
    q('FEATURE', "SELECT * FROM features WHERE ticker='GEN' ORDER BY dt DESC LIMIT 2")
    q('PRICE', "SELECT * FROM prices WHERE ticker='GEN' ORDER BY dt DESC LIMIT 2")
finally: conn.close()
