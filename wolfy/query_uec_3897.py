#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres

conn=connect_postgres()
try:
  with conn.cursor() as cur:
    for table in ['agent_tasks','alpha_search_leads','scanner_results','strategy_rules','signals','setups','prices','features','agent_artifacts']:
      cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",(table,))
      print('COLS',table,[r[0] for r in cur.fetchall()])
    queries=[
      ("TASK","SELECT * FROM agent_tasks WHERE id=3897",()),
      ("LEADS","SELECT * FROM alpha_search_leads WHERE ticker='UEC' ORDER BY id DESC LIMIT 20",()),
      ("SCANNER","SELECT * FROM scanner_results WHERE ticker='UEC' ORDER BY id DESC LIMIT 20",()),
      ("ARTIFACTS","SELECT id,artifact_type,title,body,source_url,source_fingerprint,created_at FROM agent_artifacts WHERE %s=ANY(ticker_symbols) OR title ILIKE %s ORDER BY id DESC LIMIT 20",('UEC','%UEC%')),
      ("SIGNALS","SELECT * FROM signals WHERE ticker='UEC' ORDER BY dt DESC LIMIT 20",()),
      ("SETUPS","SELECT * FROM setups WHERE ticker='UEC' ORDER BY id DESC LIMIT 20",()),
      ("PRICES","SELECT * FROM prices WHERE ticker='UEC' ORDER BY dt DESC LIMIT 5",()),
      ("FEATURES","SELECT * FROM features WHERE ticker='UEC' ORDER BY dt DESC LIMIT 5",()),
      ("RUN384","SELECT id,ticker,score,data_date,close,r20,notes,created_at FROM scanner_results WHERE run_id=384 ORDER BY id",()),
      ("APPROVED","SELECT * FROM strategy_rules WHERE status='approved' ORDER BY id",()),
    ]
    for label,q,p in queries:
      try:
        cur.execute(q,p); cols=[d.name for d in cur.description]
        print(label,json.dumps([dict(zip(cols,r)) for r in cur.fetchall()],default=str,indent=2))
      except Exception as e:
        conn.rollback(); print(label,'ERROR',repr(e))
finally: conn.close()
