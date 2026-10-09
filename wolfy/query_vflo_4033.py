#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres

conn = connect_postgres()
try:
    with conn.cursor() as cur:
        queries = {
            'LEAD': ("SELECT * FROM alpha_search_leads WHERE ticker='VFLO' ORDER BY id DESC LIMIT 5", ()),
            'SCANNER': ("SELECT * FROM scanner_results WHERE ticker='VFLO' ORDER BY id DESC LIMIT 10", ()),
            'SIGNALS': ("SELECT * FROM signals WHERE ticker='VFLO' LIMIT 10", ()),
            'SETUPS': ("SELECT * FROM setups WHERE ticker='VFLO' ORDER BY id DESC LIMIT 10", ()),
            'RULES': ("SELECT * FROM strategy_rules WHERE status='approved' ORDER BY id", ()),
            'ARTIFACTS': ("SELECT id,title,source_fingerprint,created_at FROM agent_artifacts WHERE 'VFLO'=ANY(ticker_symbols) ORDER BY created_at DESC LIMIT 10", ()),
        }
        run_id = None
        for label, (sql, params) in queries.items():
            try:
                cur.execute(sql, params)
                cols = [d.name for d in cur.description]
                rows = [dict(zip(cols, row)) for row in cur.fetchall()]
                print(label, json.dumps(rows, default=str, indent=2))
                if label == 'SCANNER' and rows:
                    run_id = rows[0].get('run_id')
            except Exception as exc:
                print(label, 'ERROR', exc)
                conn.rollback()
        if run_id is not None:
            cur.execute("SELECT id,run_id,ticker,data_date,close,score,r20,notes,created_at FROM scanner_results WHERE run_id=%s ORDER BY score DESC", (run_id,))
            cols = [d.name for d in cur.description]
            print('RUN', json.dumps([dict(zip(cols, row)) for row in cur.fetchall()], default=str, indent=2))
finally:
    conn.close()
