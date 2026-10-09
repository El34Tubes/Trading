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
        dump('TASK', 'SELECT * FROM agent_tasks WHERE id=%s', (4086,))
        dump('KO_LEADS', "SELECT * FROM alpha_search_leads WHERE ticker='KO' OR title ILIKE '%%KO%%' ORDER BY id DESC LIMIT 20")
        dump('KO_SCANNER', "SELECT * FROM scanner_results WHERE ticker='KO' ORDER BY id DESC LIMIT 10")
        dump('RUN_ROWS', "SELECT * FROM scanner_results WHERE run_id=(SELECT run_id FROM scanner_results WHERE ticker='KO' ORDER BY id DESC LIMIT 1) ORDER BY id")
        dump('KO_FEATURES', "SELECT * FROM features WHERE ticker='KO' ORDER BY date DESC LIMIT 5")
        dump('KO_PRICES', "SELECT * FROM prices WHERE ticker='KO' ORDER BY date DESC LIMIT 5")
        dump('KO_SIGNALS', "SELECT * FROM signals WHERE ticker='KO' ORDER BY created_at DESC LIMIT 10")
        dump('KO_SETUPS', "SELECT * FROM setups WHERE ticker='KO' ORDER BY created_at DESC LIMIT 10")
        dump('APPROVED_RULES', "SELECT * FROM strategy_rules WHERE status='approved' ORDER BY id")
        dump('EXISTING_KO_RESEARCH', "SELECT id,title,body,source_url,source_fingerprint,created_at FROM agent_artifacts WHERE 'KO'=ANY(ticker_symbols) ORDER BY id DESC LIMIT 10")
finally:
    conn.close()
