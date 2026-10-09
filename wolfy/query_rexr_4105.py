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
        dump('TASK', 'SELECT * FROM agent_tasks WHERE id=%s', (4105,))
        dump('REXR_LEADS', "SELECT * FROM alpha_search_leads WHERE ticker='REXR' OR title ILIKE '%%REXR%%' ORDER BY id DESC LIMIT 20")
        dump('REXR_SCANNER', "SELECT * FROM scanner_results WHERE ticker='REXR' ORDER BY id DESC LIMIT 10")
        dump('RUN_ROWS', "SELECT * FROM scanner_results WHERE run_id=(SELECT run_id FROM scanner_results WHERE ticker='REXR' ORDER BY id DESC LIMIT 1) ORDER BY id")
        dump('REXR_FEATURES', "SELECT * FROM features WHERE ticker='REXR' ORDER BY dt DESC LIMIT 5")
        dump('REXR_PRICES', "SELECT * FROM prices WHERE ticker='REXR' ORDER BY dt DESC LIMIT 5")
        dump('REXR_SIGNALS', "SELECT * FROM signals WHERE ticker='REXR' ORDER BY dt DESC LIMIT 10")
        dump('REXR_SETUPS', "SELECT * FROM setups WHERE ticker='REXR' ORDER BY id DESC LIMIT 10")
        dump('APPROVED_RULES', "SELECT * FROM strategy_rules WHERE status='approved' ORDER BY id")
        dump('EXISTING_REXR_RESEARCH', "SELECT id,title,body,source_url,source_fingerprint,created_at FROM agent_artifacts WHERE 'REXR'=ANY(ticker_symbols) ORDER BY id DESC LIMIT 10")
finally:
    conn.close()
