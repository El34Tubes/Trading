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
        dump('TASK', 'SELECT * FROM agent_tasks WHERE id=%s', (4070,))
        dump('GEN_LEADS', "SELECT * FROM alpha_search_leads WHERE ticker='GEN' OR title ILIKE '%%GEN%%' ORDER BY id DESC LIMIT 20")
        dump('GEN_SCANNER', "SELECT * FROM scanner_results WHERE ticker='GEN' ORDER BY id DESC LIMIT 10")
        dump('RUN_ROWS', "SELECT * FROM scanner_results WHERE run_id=(SELECT run_id FROM scanner_results WHERE ticker='GEN' ORDER BY id DESC LIMIT 1) ORDER BY id")
        dump('GEN_FEATURES', "SELECT * FROM features WHERE ticker='GEN' ORDER BY date DESC LIMIT 5")
        dump('GEN_PRICES', "SELECT * FROM prices WHERE ticker='GEN' ORDER BY date DESC LIMIT 5")
        dump('GEN_SIGNALS', "SELECT * FROM signals WHERE ticker='GEN' ORDER BY created_at DESC LIMIT 10")
        dump('GEN_SETUPS', "SELECT * FROM setups WHERE ticker='GEN' ORDER BY created_at DESC LIMIT 10")
        dump('APPROVED_RULES', "SELECT * FROM strategy_rules WHERE status='approved' ORDER BY id")
        dump('EXISTING_GEN_RESEARCH', "SELECT id,title,body,source_url,source_fingerprint,created_at FROM agent_artifacts WHERE 'GEN'=ANY(ticker_symbols) ORDER BY id DESC LIMIT 10")
finally:
    conn.close()
