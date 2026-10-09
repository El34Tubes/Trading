#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres

conn=connect_postgres()
try:
    with conn.cursor() as cur:
        queries = {
            'task': "SELECT * FROM agent_tasks WHERE id=3893",
            'leads': "SELECT * FROM alpha_search_leads WHERE ticker='SPYM' ORDER BY id DESC LIMIT 10",
            'scanner': "SELECT * FROM scanner_results WHERE ticker='SPYM' ORDER BY id DESC LIMIT 10",
            'strategies': "SELECT * FROM strategy_rules WHERE status='approved' ORDER BY id DESC LIMIT 20",
            'signals': "SELECT * FROM signals WHERE ticker='SPYM' ORDER BY id DESC LIMIT 10",
            'setups': "SELECT * FROM setups WHERE ticker='SPYM' ORDER BY id DESC LIMIT 10",
        }
        for name,q in queries.items():
            try:
                cur.execute(q)
                cols=[d.name for d in cur.description]
                rows=[dict(zip(cols,r)) for r in cur.fetchall()]
                print('\n###',name)
                print(json.dumps(rows,default=str,indent=2))
            except Exception as exc:
                conn.rollback()
                print('\n###',name,'ERROR',repr(exc))
finally:
    conn.close()
