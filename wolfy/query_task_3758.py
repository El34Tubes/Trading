#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres
conn=connect_postgres()
try:
  with conn.cursor() as cur:
    for table in ['alpha_search_leads','signals','setups','prices']:
      cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",(table,))
      print(table,[r[0] for r in cur.fetchall()])
    cur.execute("SELECT * FROM alpha_search_leads WHERE ticker='GM' ORDER BY id DESC LIMIT 5")
    cols=[d.name for d in cur.description]
    print('LEADS',json.dumps([dict(zip(cols,r)) for r in cur.fetchall()],default=str,indent=2))
    cur.execute("SELECT * FROM signals WHERE ticker='GM' ORDER BY id DESC LIMIT 10")
    cols=[d.name for d in cur.description]
    print('SIGNALS',json.dumps([dict(zip(cols,r)) for r in cur.fetchall()],default=str,indent=2))
    cur.execute("SELECT * FROM setups WHERE ticker='GM' ORDER BY id DESC LIMIT 10")
    cols=[d.name for d in cur.description]
    print('SETUPS',json.dumps([dict(zip(cols,r)) for r in cur.fetchall()],default=str,indent=2))
    cur.execute("SELECT min(dt),max(dt),count(*) FROM prices WHERE ticker='GM'")
    print('PRICES',cur.fetchall())
finally:
  conn.close()
