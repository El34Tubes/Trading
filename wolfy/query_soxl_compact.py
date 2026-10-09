#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres
conn=connect_postgres()
try:
    with conn.cursor() as cur:
        for label,sql in [
          ('RUN_CHECK', "SELECT count(*) n,count(*) FILTER (WHERE ticker IN ('SPY','QQQ')) benchmarks,count(*) FILTER (WHERE (notes->>'rs_spy_20')::double precision=r20 AND (notes->>'rs_qqq_20')::double precision=r20) self_rs FROM scanner_results WHERE run_id=378"),
          ('SIGNALS', "SELECT count(*) n FROM signals WHERE ticker='SOXL'"),
          ('SETUPS', "SELECT count(*) n FROM setups WHERE ticker='SOXL'"),
          ('RULES', "SELECT id,rule_name,rule_type,status,description,parameters FROM strategy_rules WHERE status='approved' ORDER BY id")]:
            cur.execute(sql)
            cols=[d.name for d in cur.description]
            print(label,json.dumps([dict(zip(cols,r)) for r in cur.fetchall()],default=str,indent=2))
finally:
    conn.close()
