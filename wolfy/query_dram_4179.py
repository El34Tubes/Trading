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
        dump('TASK', 'SELECT * FROM agent_tasks WHERE id=%s', (4179,))
        dump('DRAM_LEADS', "SELECT * FROM alpha_search_leads WHERE ticker='DRAM' OR title ILIKE '%%DRAM%%' ORDER BY id DESC LIMIT 20")
        dump('DRAM_SCANNER', "SELECT * FROM scanner_results WHERE ticker='DRAM' ORDER BY id DESC LIMIT 10")
        dump('RUN_ROWS', "SELECT * FROM scanner_results WHERE run_id=(SELECT run_id FROM scanner_results WHERE ticker='DRAM' ORDER BY id DESC LIMIT 1) ORDER BY id")
        dump('DRAM_FEATURES', "SELECT * FROM features WHERE ticker='DRAM' ORDER BY date DESC LIMIT 5")
        dump('DRAM_PRICES', "SELECT * FROM prices WHERE ticker='DRAM' ORDER BY date DESC LIMIT 5")
        dump('DRAM_SIGNALS', "SELECT * FROM signals WHERE ticker='DRAM' ORDER BY created_at DESC LIMIT 10")
        dump('DRAM_SETUPS', "SELECT * FROM setups WHERE ticker='DRAM' ORDER BY created_at DESC LIMIT 10")
        dump('APPROVED_RULES', "SELECT * FROM strategy_rules WHERE status='approved' ORDER BY id")
        dump('EXISTING_DRAM_RESEARCH', "SELECT id,title,body,source_url,source_fingerprint,created_at FROM agent_artifacts WHERE 'DRAM'=ANY(ticker_symbols) OR title ILIKE '%%DRAM%%' ORDER BY id DESC LIMIT 20")
finally:
    conn.close()
