#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres

conn = connect_postgres()
try:
    with conn.cursor() as cur:
        queries = {
            'TASK': ("SELECT * FROM agent_tasks WHERE id=%s", (4045,)),
            'LEADS': ("SELECT * FROM alpha_search_leads WHERE ticker=%s ORDER BY id DESC LIMIT 10", ('BUFR',)),
            'SCANNER': ("SELECT * FROM scanner_results WHERE ticker=%s ORDER BY id DESC LIMIT 10", ('BUFR',)),
            'FEATURES': ("SELECT * FROM features WHERE ticker=%s ORDER BY dt DESC LIMIT 10", ('BUFR',)),
            'PRICES': ("SELECT * FROM prices WHERE ticker=%s ORDER BY dt DESC LIMIT 10", ('BUFR',)),
            'SIGNALS': ("SELECT * FROM signals WHERE ticker=%s LIMIT 10", ('BUFR',)),
            'SETUPS': ("SELECT * FROM setups WHERE ticker=%s ORDER BY id DESC LIMIT 10", ('BUFR',)),
            'RULES': ("SELECT * FROM strategy_rules WHERE status='approved' ORDER BY id", ()),
            'RUN468': ("SELECT ticker,r20,notes FROM scanner_results WHERE run_id=468 ORDER BY ticker", ()),
            'SCHEMAS': ("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public' AND table_name IN ('features','prices','signals','setups','strategy_rules') ORDER BY table_name,ordinal_position", ()),
            'ARTIFACTS': ("SELECT id,title,source_fingerprint,created_at FROM agent_artifacts WHERE %s=ANY(ticker_symbols) ORDER BY id DESC LIMIT 10", ('BUFR',)),
        }
        for label, (sql, params) in queries.items():
            print(f'---{label}---')
            try:
                cur.execute(sql, params)
                cols = [d.name for d in cur.description]
                for row in cur.fetchall():
                    print(json.dumps(dict(zip(cols, row)), default=str, sort_keys=True))
            except Exception as exc:
                conn.rollback()
                print(f'ERROR {exc}')
finally:
    conn.close()
