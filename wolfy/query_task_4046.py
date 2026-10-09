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
        dump('TASK', 'SELECT * FROM agent_tasks WHERE id=%s', (4046,))
        dump('MATCHING_LEADS', "SELECT * FROM alpha_search_leads WHERE source_fingerprint=%s OR id::text=%s ORDER BY id DESC LIMIT 20", ('6a7d9549ce93aa7aae15f3402d2b2b7e4300fa9e4b6ea0f217d19b3e7d613c3e','4046'))
        dump('RECENT_LEADS', "SELECT * FROM alpha_search_leads ORDER BY created_at DESC LIMIT 15")
        dump('ARTIFACT_COLS', "SELECT column_name,data_type FROM information_schema.columns WHERE table_schema='public' AND table_name='agent_artifacts' ORDER BY ordinal_position")
        dump('CHUNK_COLS', "SELECT column_name,data_type FROM information_schema.columns WHERE table_schema='public' AND table_name='knowledge_chunks' ORDER BY ordinal_position")
finally:
    conn.close()
