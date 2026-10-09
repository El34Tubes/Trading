#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres
conn=connect_postgres()
try:
 with conn.cursor() as cur:
  def d(label,sql,p=()):
   cur.execute(sql,p); cols=[x.name for x in cur.description]; print(label,json.dumps([dict(zip(cols,r)) for r in cur.fetchall()],default=str,indent=2))
  d('RUN_AUDIT',"""SELECT count(*) n, count(*) FILTER (WHERE ticker IN ('SPY','QQQ')) benchmarks,
      count(*) FILTER (WHERE (notes->>'rs_spy_20')::double precision=r20) rs_spy_equals_own_r20,
      count(*) FILTER (WHERE (notes->>'rs_qqq_20')::double precision=r20) rs_qqq_equals_own_r20,
      min(created_at) created_min,max(created_at) created_max FROM scanner_results WHERE run_id=522""")
  d('SIGNALS',"SELECT * FROM signals WHERE ticker='ACYN' LIMIT 20")
  d('SETUPS',"SELECT * FROM setups WHERE ticker='ACYN' LIMIT 20")
  d('APPROVED_RULES',"SELECT * FROM strategy_rules WHERE status='approved' ORDER BY id")
  d('EXISTING',"SELECT id,title,source_fingerprint,created_at FROM agent_artifacts WHERE 'ACYN'=ANY(ticker_symbols) ORDER BY id DESC")
except Exception:
 conn.rollback(); raise
finally: conn.close()
