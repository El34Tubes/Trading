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
        dump('TASK', 'SELECT * FROM agent_tasks WHERE id=%s', (4139,))
        dump('LEADS', "SELECT * FROM alpha_search_leads WHERE ticker='ACVA' ORDER BY id DESC LIMIT 10")
        dump('SCANNER_RESULTS', "SELECT * FROM scanner_results WHERE ticker='ACVA' ORDER BY id DESC LIMIT 10")
        dump('RUN_ROWS', "SELECT ticker,run_id,created_at,close,r20,rs_spy_20,rs_qqq_20,volume_surge_1d_20,breakout_20d_pct,score,rank_reasons FROM scanner_results WHERE run_id=(SELECT run_id FROM scanner_results WHERE ticker='ACVA' ORDER BY id DESC LIMIT 1) ORDER BY ticker")
        dump('SIGNALS', "SELECT * FROM signals WHERE ticker='ACVA' ORDER BY created_at DESC LIMIT 10")
        dump('SETUPS', "SELECT * FROM setups WHERE ticker='ACVA' ORDER BY created_at DESC LIMIT 10")
        dump('APPROVED_RULES', "SELECT * FROM strategy_rules WHERE status='approved' ORDER BY id")
        dump('EXISTING_RESEARCH', "SELECT id,title,body,source_url,source_fingerprint,created_at FROM agent_artifacts WHERE 'ACVA'=ANY(ticker_symbols) ORDER BY id DESC LIMIT 10")
finally:
    conn.close()
