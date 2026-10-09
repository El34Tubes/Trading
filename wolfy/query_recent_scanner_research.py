#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres
conn=connect_postgres()
try:
  with conn.cursor() as cur:
    cur.execute("SELECT id,title,body,source_url,source_fingerprint,topic_tags,ticker_symbols,created_at FROM agent_artifacts WHERE artifact_type='scanner_alpha_research' ORDER BY id DESC LIMIT 10")
    cols=[d.name for d in cur.description]
    print(json.dumps([dict(zip(cols,r)) for r in cur.fetchall()],default=str,indent=2))
    cur.execute("SELECT status,count(*) FROM alpha_leads GROUP BY status ORDER BY count(*) DESC")
    print('STATUSES',cur.fetchall())
finally: conn.close()
