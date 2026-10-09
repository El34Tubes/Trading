#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres
conn=connect_postgres()
try:
  with conn.cursor() as cur:
    for table in ['agent_tasks','alpha_search_leads','scanner_results','signals','setups']:
      cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",(table,))
      print('\nCOLUMNS',table,[r[0] for r in cur.fetchall()])
    for label,sql,args in [
      ('TASK','SELECT * FROM agent_tasks WHERE id=%s',(3894,)),
      ('LEADS',"SELECT * FROM alpha_search_leads WHERE ticker='SPYV' ORDER BY id DESC LIMIT 10",()),
      ('SCANNER',"SELECT * FROM scanner_results WHERE ticker='SPYV' ORDER BY id DESC LIMIT 10",()),
      ('SIGNALS',"SELECT * FROM signals WHERE ticker='SPYV' ORDER BY id DESC LIMIT 10",()),
      ('SETUPS',"SELECT * FROM setups WHERE ticker='SPYV' ORDER BY id DESC LIMIT 10",()),
      ('STRATEGIES',"SELECT * FROM strategy_rules WHERE status='approved' ORDER BY id DESC LIMIT 10",()),
    ]:
      try:
        cur.execute(sql,args)
        cols=[d.name for d in cur.description]
        print('\n'+label,json.dumps([dict(zip(cols,r)) for r in cur.fetchall()],default=str,indent=2))
      except Exception as e:
        print('\n'+label,'ERROR',repr(e)); conn.rollback()
finally: conn.close()
