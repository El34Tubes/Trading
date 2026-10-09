#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres

conn = connect_postgres()
try:
    with conn.cursor() as cur:
        for table in ['agent_tasks','alpha_search_leads','scanner_results','signals','setups','prices','strategy_rules']:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position", (table,))
            print(table, [r[0] for r in cur.fetchall()])
        cur.execute("SELECT * FROM agent_tasks WHERE id=3878")
        cols=[d.name for d in cur.description]
        print('TASK', json.dumps([dict(zip(cols,r)) for r in cur.fetchall()], default=str, indent=2))
        cur.execute("SELECT * FROM alpha_search_leads WHERE ticker='LAES' ORDER BY id DESC LIMIT 10")
        cols=[d.name for d in cur.description]
        print('LEADS', json.dumps([dict(zip(cols,r)) for r in cur.fetchall()], default=str, indent=2))
        cur.execute("SELECT * FROM scanner_results WHERE ticker='LAES' ORDER BY id DESC LIMIT 10")
        cols=[d.name for d in cur.description]
        print('SCANNER', json.dumps([dict(zip(cols,r)) for r in cur.fetchall()], default=str, indent=2))
        cur.execute("SELECT * FROM signals WHERE ticker='LAES' ORDER BY id DESC LIMIT 10")
        cols=[d.name for d in cur.description]
        print('SIGNALS', json.dumps([dict(zip(cols,r)) for r in cur.fetchall()], default=str, indent=2))
        cur.execute("SELECT * FROM setups WHERE ticker='LAES' ORDER BY id DESC LIMIT 10")
        cols=[d.name for d in cur.description]
        print('SETUPS', json.dumps([dict(zip(cols,r)) for r in cur.fetchall()], default=str, indent=2))
        cur.execute("SELECT min(dt),max(dt),count(*) FROM prices WHERE ticker='LAES'")
        print('PRICES', cur.fetchall())
        cur.execute("SELECT id,rule_name,rule_type,status,description,parameters FROM strategy_rules WHERE status='approved' ORDER BY id")
        cols=[d.name for d in cur.description]
        print('APPROVED_RULES', json.dumps([dict(zip(cols,r)) for r in cur.fetchall()], default=str, indent=2))
finally:
    conn.close()
