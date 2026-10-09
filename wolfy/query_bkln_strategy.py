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
        dump('SIGNAL_COLS', "SELECT column_name FROM information_schema.columns WHERE table_name='signals' ORDER BY ordinal_position")
        dump('SETUP_COLS', "SELECT column_name FROM information_schema.columns WHERE table_name='setups' ORDER BY ordinal_position")
        dump('SIGNALS', "SELECT * FROM signals WHERE ticker='BKLN' LIMIT 20")
        dump('SETUPS', "SELECT * FROM setups WHERE ticker='BKLN' LIMIT 20")
        dump('RULE_COLS', "SELECT column_name FROM information_schema.columns WHERE table_name='strategy_rules' ORDER BY ordinal_position")
        dump('RULE4070', "SELECT * FROM strategy_rules WHERE id=4070")
finally:
    conn.close()
