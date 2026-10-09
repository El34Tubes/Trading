#!/usr/bin/env python3
import json
from wolfy_db import connect_postgres
conn=connect_postgres()
try:
  with conn.cursor() as cur:
    def q(label,sql,p=()):
      cur.execute(sql,p); cols=[d.name for d in cur.description]
      print(label+'='+json.dumps([dict(zip(cols,r)) for r in cur.fetchall()],default=str))
    q('LEAD',"SELECT id,ticker,title,status,scanner_type,scanner_run_id,market_context,raw_payload,source_fingerprint FROM alpha_search_leads WHERE ticker='KO' ORDER BY id DESC LIMIT 5")
    q('SCANNER',"SELECT id,run_id,ticker,score,data_date,close,r5,r20,r60,vs20,vs50,atr,avg_volume,high20,low20,extension_penalty,liquidity_pass,notes,created_at FROM scanner_results WHERE run_id=490 AND ticker='KO'")
    q('RUN_CHECK',"SELECT count(*) n, bool_or(ticker='SPY') has_spy, bool_or(ticker='QQQ') has_qqq, min(created_at) created, array_agg(ticker ORDER BY id) tickers FROM scanner_results WHERE run_id=490")
    q('SIGNALS',"SELECT ticker,dt,strategy_id,direction,raw FROM signals WHERE ticker='KO' ORDER BY dt DESC LIMIT 10")
    q('SETUPS',"SELECT * FROM setups WHERE ticker='KO' ORDER BY created_dt DESC LIMIT 10")
    q('RULES',"SELECT id,name,status,description,metadata,rule_body FROM strategy_rules WHERE status='approved' ORDER BY id")
    q('EXISTING',"SELECT id,title,source_fingerprint,created_at FROM agent_artifacts WHERE 'KO'=ANY(ticker_symbols) ORDER BY id DESC LIMIT 10")
finally: conn.close()
