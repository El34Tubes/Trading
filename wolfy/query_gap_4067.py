#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres

conn = connect_postgres()
try:
    with conn.cursor() as cur:
        for table in ['agent_tasks','alpha_search_leads','scanner_results','scanner_runs','strategy_rules','signals','setups']:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position", (table,))
            print(f"COLUMNS {table}: {[r[0] for r in cur.fetchall()]}")
        cur.execute("SELECT * FROM agent_tasks WHERE id=4067")
        print('TASK:', json.dumps(dict(zip([d.name for d in cur.description], cur.fetchone())), default=str, indent=2))
        cur.execute("SELECT * FROM alpha_search_leads WHERE ticker='GAP' ORDER BY id DESC LIMIT 10")
        rows=cur.fetchall(); cols=[d.name for d in cur.description]
        print('LEADS:', json.dumps([dict(zip(cols,r)) for r in rows], default=str, indent=2))
        cur.execute("SELECT * FROM scanner_results WHERE ticker='GAP' ORDER BY id DESC LIMIT 10")
        rows=cur.fetchall(); cols=[d.name for d in cur.description]
        print('RESULTS:', json.dumps([dict(zip(cols,r)) for r in rows], default=str, indent=2))
        cur.execute("SELECT * FROM strategy_rules WHERE status='approved' ORDER BY id")
        rows=cur.fetchall(); cols=[d.name for d in cur.description]
        print('APPROVED_RULES:', json.dumps([dict(zip(cols,r)) for r in rows], default=str, indent=2))
        cur.execute("SELECT * FROM signals WHERE ticker='GAP' ORDER BY id DESC LIMIT 10")
        rows=cur.fetchall(); cols=[d.name for d in cur.description]
        print('SIGNALS:', json.dumps([dict(zip(cols,r)) for r in rows], default=str, indent=2))
        cur.execute("SELECT * FROM setups WHERE ticker='GAP' ORDER BY id DESC LIMIT 10")
        rows=cur.fetchall(); cols=[d.name for d in cur.description]
        print('SETUPS:', json.dumps([dict(zip(cols,r)) for r in rows], default=str, indent=2))
finally:
    conn.close()
