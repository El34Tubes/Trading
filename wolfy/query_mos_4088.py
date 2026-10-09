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
        dump('TASK', 'SELECT * FROM agent_tasks WHERE id=%s', (4088,))
        dump('MOS_LEADS', "SELECT * FROM alpha_search_leads WHERE ticker='MOS' OR title ILIKE '%%MOS%%' ORDER BY id DESC LIMIT 20")
        dump('MOS_SCANNER', "SELECT * FROM scanner_results WHERE ticker='MOS' ORDER BY id DESC LIMIT 10")
        dump('RUN_ROWS', "SELECT * FROM scanner_results WHERE run_id=(SELECT run_id FROM scanner_results WHERE ticker='MOS' ORDER BY id DESC LIMIT 1) ORDER BY id")
        dump('MOS_FEATURES', "SELECT * FROM features WHERE ticker='MOS' ORDER BY dt DESC LIMIT 5")
        dump('MOS_PRICES', "SELECT * FROM prices WHERE ticker='MOS' ORDER BY dt DESC LIMIT 5")
        dump('MOS_SIGNALS', "SELECT * FROM signals WHERE ticker='MOS' ORDER BY dt DESC LIMIT 10")
        dump('MOS_SETUPS', "SELECT * FROM setups WHERE ticker='MOS' ORDER BY id DESC LIMIT 10")
        dump('APPROVED_RULES', "SELECT * FROM strategy_rules WHERE status='approved' ORDER BY id")
        dump('EXISTING_MOS_RESEARCH', "SELECT id,title,body,source_url,source_fingerprint,created_at FROM agent_artifacts WHERE 'MOS'=ANY(ticker_symbols) ORDER BY id DESC LIMIT 10")
finally:
    conn.close()
