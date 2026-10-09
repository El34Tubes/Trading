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
        dump('TASK', 'SELECT * FROM agent_tasks WHERE id=%s', (4116,))
        dump('TGT_LEADS', "SELECT * FROM alpha_search_leads WHERE ticker='TGT' OR title ILIKE '%%TGT%%' ORDER BY id DESC LIMIT 20")
        dump('TGT_SCANNER', "SELECT * FROM scanner_results WHERE ticker='TGT' ORDER BY id DESC LIMIT 10")
        dump('RUN_ROWS', "SELECT * FROM scanner_results WHERE run_id=(SELECT run_id FROM scanner_results WHERE ticker='TGT' ORDER BY id DESC LIMIT 1) ORDER BY id")
        dump('TGT_FEATURES', "SELECT * FROM features WHERE ticker='TGT' ORDER BY dt DESC LIMIT 5")
        dump('TGT_PRICES', "SELECT * FROM prices WHERE ticker='TGT' ORDER BY dt DESC LIMIT 5")
        dump('TGT_SIGNALS', "SELECT * FROM signals WHERE ticker='TGT' ORDER BY dt DESC LIMIT 10")
        dump('TGT_SETUPS', "SELECT * FROM setups WHERE ticker='TGT' ORDER BY id DESC LIMIT 10")
        dump('APPROVED_RULES', "SELECT * FROM strategy_rules WHERE status='approved' ORDER BY id")
        dump('EXISTING_TGT_RESEARCH', "SELECT id,title,body,source_url,source_fingerprint,created_at FROM agent_artifacts WHERE 'TGT'=ANY(ticker_symbols) ORDER BY id DESC LIMIT 10")
finally:
    conn.close()
