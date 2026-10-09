#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres

def dump(label, sql, params=()):
    cur.execute(sql, params)
    cols=[d.name for d in cur.description]
    print('\n###', label)
    for row in cur.fetchall():
        print(json.dumps(dict(zip(cols,row)), default=str, sort_keys=True))

conn=connect_postgres()
try:
    with conn.cursor() as cur:
        dump('TASK', 'SELECT * FROM agent_tasks WHERE id=%s', (4138,))
        dump('LEADS', "SELECT * FROM alpha_search_leads WHERE ticker='ABUS' ORDER BY id DESC LIMIT 10")
        dump('SCANNER_RESULTS', "SELECT * FROM scanner_results WHERE ticker='ABUS' ORDER BY id DESC LIMIT 10")
        dump('SIGNALS', "SELECT * FROM signals WHERE ticker='ABUS' ORDER BY created_at DESC LIMIT 10")
        dump('SETUPS', "SELECT * FROM setups WHERE ticker='ABUS' ORDER BY created_at DESC LIMIT 10")
        dump('APPROVED_RULES', "SELECT * FROM strategy_rules WHERE status='approved' ORDER BY id")
        dump('EXISTING_RESEARCH', "SELECT id,title,body,source_url,source_fingerprint,created_at FROM agent_artifacts WHERE 'ABUS'=ANY(ticker_symbols) ORDER BY id DESC LIMIT 10")
finally:
    conn.close()
