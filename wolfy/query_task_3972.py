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
        dump('TASK', 'SELECT * FROM agent_tasks WHERE id=%s', (3972,))
        dump('LEADS', "SELECT * FROM alpha_search_leads WHERE ticker='BKR' ORDER BY id DESC LIMIT 10")
        dump('SCANNER', "SELECT * FROM scanner_results WHERE ticker='BKR' ORDER BY id DESC LIMIT 10")
        dump('RUN_ROWS', "SELECT * FROM scanner_results WHERE run_id=(SELECT run_id FROM scanner_results WHERE ticker='BKR' ORDER BY id DESC LIMIT 1) ORDER BY score DESC")
        dump('SIGNALS', "SELECT * FROM signals WHERE ticker='BKR' ORDER BY id DESC LIMIT 10")
        dump('SETUPS', "SELECT * FROM setups WHERE ticker='BKR' ORDER BY id DESC LIMIT 10")
        dump('RULES', "SELECT id,rule_name,rule_type,status,description,parameters FROM strategy_rules WHERE status='approved' ORDER BY id")
        dump('ARTIFACTS', "SELECT id,title,source_fingerprint,created_at FROM agent_artifacts WHERE 'BKR'=ANY(ticker_symbols) ORDER BY id DESC LIMIT 10")
finally:
    conn.close()
