#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres
conn=connect_postgres()
try:
    with conn.cursor() as cur:
        def dump(label, sql, params=()):
            cur.execute(sql, params)
            cols=[d.name for d in cur.description]
            print(label, json.dumps([dict(zip(cols,r)) for r in cur.fetchall()], default=str, indent=2))
        dump('TASK', 'SELECT * FROM agent_tasks WHERE id=%s', (3891,))
        dump('LEADS', "SELECT * FROM alpha_search_leads WHERE ticker='SOUN' ORDER BY id DESC LIMIT 10")
        dump('SCANNER', "SELECT * FROM scanner_results WHERE ticker='SOUN' ORDER BY id DESC LIMIT 10")
        dump('SIGNALS', "SELECT * FROM signals WHERE ticker='SOUN' ORDER BY id DESC LIMIT 10")
        dump('SETUPS', "SELECT * FROM setups WHERE ticker='SOUN' ORDER BY id DESC LIMIT 10")
        dump('PRICES', "SELECT * FROM prices WHERE ticker='SOUN' ORDER BY trade_date DESC LIMIT 10")
        dump('PRIOR_ARTIFACTS', "SELECT id,title,created_at,source_url,body FROM agent_artifacts WHERE 'SOUN'=ANY(ticker_symbols) ORDER BY id DESC LIMIT 10")
        dump('RULES', "SELECT id,rule_name,rule_type,status,description,parameters FROM strategy_rules WHERE status IN ('approved','active','candidate') ORDER BY id")
finally:
    conn.close()
