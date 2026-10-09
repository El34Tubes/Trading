#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres

conn = connect_postgres()
try:
    with conn.cursor() as cur:
        def dump(label, sql, params=()):
            cur.execute(sql, params)
            cols = [d.name for d in cur.description]
            print(label, json.dumps([dict(zip(cols, r)) for r in cur.fetchall()], default=str, indent=2))
        dump('TASK', 'SELECT * FROM agent_tasks WHERE id=%s', (4135,))
        dump('VZ_LEADS', "SELECT * FROM alpha_search_leads WHERE ticker='VZ' OR title ILIKE '%%VZ%%' ORDER BY id DESC LIMIT 20")
        dump('VZ_SCANNER', "SELECT * FROM scanner_results WHERE ticker='VZ' ORDER BY id DESC LIMIT 10")
        dump('RUN_ROWS', "SELECT * FROM scanner_results WHERE run_id=(SELECT run_id FROM scanner_results WHERE ticker='VZ' ORDER BY id DESC LIMIT 1) ORDER BY id")
        dump('VZ_FEATURES', "SELECT * FROM features WHERE ticker='VZ' ORDER BY dt DESC LIMIT 5")
        dump('VZ_PRICES', "SELECT * FROM prices WHERE ticker='VZ' ORDER BY dt DESC LIMIT 5")
        dump('VZ_SIGNALS', "SELECT * FROM signals WHERE ticker='VZ' ORDER BY dt DESC LIMIT 10")
        dump('VZ_SETUPS', "SELECT * FROM setups WHERE ticker='VZ' ORDER BY id DESC LIMIT 10")
        dump('APPROVED_RULES', "SELECT * FROM strategy_rules WHERE status='approved' ORDER BY id")
        dump('EXISTING_VZ_RESEARCH', "SELECT id,title,body,source_url,source_fingerprint,created_at FROM agent_artifacts WHERE 'VZ'=ANY(ticker_symbols) ORDER BY id DESC LIMIT 10")
finally:
    conn.close()
