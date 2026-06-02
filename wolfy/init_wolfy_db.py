#!/usr/bin/env python3
"""Initialize Wolfy's local SQLite research/portfolio database."""
from __future__ import annotations
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

BASE = Path('/root/.hermes/wolfy')
DB = BASE / 'wolfy.db'
BASE.mkdir(parents=True, exist_ok=True)

SCHEMA = r'''
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA user_version=1;

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS automation_allowlist (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_type TEXT NOT NULL,
  item TEXT NOT NULL UNIQUE,
  purpose TEXT NOT NULL,
  approved_by TEXT NOT NULL DEFAULT 'user',
  approved_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS knowledge_sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  author TEXT,
  source_type TEXT NOT NULL,
  url_or_reference TEXT,
  access_mode TEXT NOT NULL DEFAULT 'public_or_user_provided',
  copyright_status TEXT DEFAULT 'unknown',
  priority INTEGER NOT NULL DEFAULT 50,
  quality_score REAL DEFAULT 0.5,
  status TEXT NOT NULL DEFAULT 'queued',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS knowledge_notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER REFERENCES knowledge_sources(id),
  topic TEXT NOT NULL,
  principle TEXT NOT NULL,
  summary TEXT NOT NULL,
  application_to_wolfy TEXT NOT NULL,
  tags TEXT,
  confidence REAL DEFAULT 0.5,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS strategy_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rule_name TEXT NOT NULL UNIQUE,
  rule_type TEXT NOT NULL,
  description TEXT NOT NULL,
  source_basis TEXT,
  implementation_status TEXT NOT NULL DEFAULT 'proposed',
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS training_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_name TEXT NOT NULL UNIQUE,
  category TEXT NOT NULL,
  objective TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 50,
  cadence TEXT NOT NULL DEFAULT 'hourly_if_tokens_available',
  status TEXT NOT NULL DEFAULT 'queued',
  last_attempt_at TEXT,
  completed_at TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS market_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  snapshot_date TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  spy_close REAL, qqq_close REAL, iwm_close REAL, dia_close REAL,
  vix_proxy REAL, rates_proxy REAL, oil_proxy REAL,
  sector_leaders TEXT,
  regime_label TEXT,
  notes TEXT,
  UNIQUE(snapshot_date)
);

CREATE TABLE IF NOT EXISTS scanner_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_time TEXT NOT NULL DEFAULT (datetime('now')),
  data_source TEXT NOT NULL,
  universe TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS scanner_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL REFERENCES scanner_runs(id) ON DELETE CASCADE,
  ticker TEXT NOT NULL,
  score REAL,
  data_date TEXT,
  close REAL,
  r5 REAL, r20 REAL, r60 REAL,
  vs20 REAL, vs50 REAL,
  atr REAL,
  avg_volume REAL,
  high20 REAL,
  low20 REAL,
  extension_penalty REAL,
  liquidity_pass INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_scanner_results_ticker ON scanner_results(ticker);
CREATE INDEX IF NOT EXISTS idx_scanner_results_run ON scanner_results(run_id, score DESC);

CREATE TABLE IF NOT EXISTS universe_symbols (
  symbol TEXT PRIMARY KEY,
  name TEXT,
  source TEXT NOT NULL,
  sector TEXT,
  is_etf INTEGER NOT NULL DEFAULT 0,
  last_seen TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_universe_symbols_active_source ON universe_symbols(active, source);
CREATE INDEX IF NOT EXISTS idx_universe_symbols_etf ON universe_symbols(is_etf, active);

CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT NOT NULL DEFAULT (datetime('now')),
  report_type TEXT NOT NULL,
  content TEXT NOT NULL,
  delivered_to TEXT,
  source_job_id TEXT
);

CREATE TABLE IF NOT EXISTS recommendations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  report_id INTEGER REFERENCES reports(id),
  timestamp TEXT NOT NULL DEFAULT (datetime('now')),
  ticker TEXT NOT NULL,
  action TEXT NOT NULL,
  recommendation_type TEXT NOT NULL,
  thesis TEXT,
  setup_type TEXT,
  entry_zone TEXT,
  entry_trigger TEXT,
  stop TEXT,
  target TEXT,
  risk_reward TEXT,
  confidence TEXT,
  position_size_suggestion TEXT,
  holding_period TEXT,
  status TEXT NOT NULL DEFAULT 'watching',
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_recs_ticker ON recommendations(ticker);
CREATE INDEX IF NOT EXISTS idx_recs_status ON recommendations(status);

CREATE TABLE IF NOT EXISTS yang_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  recommendation_id INTEGER NOT NULL REFERENCES recommendations(id) ON DELETE CASCADE,
  alpha_lead_id INTEGER REFERENCES alpha_leads(id) ON DELETE SET NULL,
  ticker TEXT NOT NULL,
  wolfy_alpha_thesis TEXT NOT NULL,
  technical_status TEXT NOT NULL,
  entry_trigger TEXT NOT NULL,
  entry_zone TEXT,
  stop_invalidation TEXT NOT NULL,
  target_exit_plan TEXT NOT NULL,
  atr REAL,
  r_multiple REAL,
  trend_read TEXT,
  relative_strength_read TEXT,
  volume_read TEXT,
  notes TEXT,
  raw_payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_yang_reviews_rec_created ON yang_reviews(recommendation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_yang_reviews_ticker_created ON yang_reviews(ticker, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_yang_reviews_status ON yang_reviews(technical_status, created_at DESC);

CREATE TABLE IF NOT EXISTS paper_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  recommendation_id INTEGER REFERENCES recommendations(id),
  ticker TEXT NOT NULL,
  entry_date TEXT,
  entry_price REAL,
  quantity REAL,
  -- Compatibility aliases for LLM/generated diagnostics and older scripts.
  -- Keep these mirrored to quantity/entry_date/exit_date when writing rows.
  qty REAL,
  opened_at TEXT,
  closed_at TEXT,
  instrument TEXT DEFAULT 'equity_or_etf',
  stop_price REAL,
  target_price REAL,
  exit_date TEXT,
  exit_price REAL,
  exit_reason TEXT,
  pnl REAL,
  r_multiple REAL,
  days_held INTEGER,
  status TEXT NOT NULL DEFAULT 'planned',
  max_favorable_excursion REAL,
  max_drawdown REAL,
  data_source TEXT,
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON paper_trades(status);
CREATE INDEX IF NOT EXISTS idx_paper_trades_recommendation ON paper_trades(recommendation_id);
CREATE INDEX IF NOT EXISTS idx_paper_trades_ticker ON paper_trades(ticker);

CREATE TRIGGER IF NOT EXISTS trg_paper_trades_alias_after_insert
AFTER INSERT ON paper_trades
FOR EACH ROW
WHEN NEW.qty IS NULL OR NEW.opened_at IS NULL OR NEW.closed_at IS NULL
BEGIN
  UPDATE paper_trades
  SET qty=COALESCE(NEW.qty, NEW.quantity),
      opened_at=COALESCE(NEW.opened_at, NEW.entry_date),
      closed_at=COALESCE(NEW.closed_at, NEW.exit_date)
  WHERE id=NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_paper_trades_alias_after_update
AFTER UPDATE OF quantity, entry_date, exit_date, qty, opened_at, closed_at ON paper_trades
FOR EACH ROW
WHEN NEW.qty IS NULL OR NEW.opened_at IS NULL OR NEW.closed_at IS NULL
BEGIN
  UPDATE paper_trades
  SET qty=COALESCE(NEW.qty, NEW.quantity),
      opened_at=COALESCE(NEW.opened_at, NEW.entry_date),
      closed_at=COALESCE(NEW.closed_at, NEW.exit_date)
  WHERE id=NEW.id;
END;

CREATE TABLE IF NOT EXISTS recommendation_outcomes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  recommendation_id INTEGER NOT NULL REFERENCES recommendations(id) ON DELETE CASCADE,
  paper_trade_id INTEGER REFERENCES paper_trades(id) ON DELETE SET NULL,
  entry_triggered INTEGER DEFAULT 0,
  hit_stop INTEGER DEFAULT 0,
  hit_target INTEGER DEFAULT 0,
  max_gain_pct REAL,
  max_drawdown_pct REAL,
  max_favorable_excursion REAL,
  max_drawdown REAL,
  r_multiple REAL,
  pnl REAL,
  days_held INTEGER,
  exit_reason TEXT,
  thesis_correct INTEGER,
  notes TEXT,
  graded_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_recommendation_outcomes_rec ON recommendation_outcomes(recommendation_id, graded_at DESC);

CREATE TABLE IF NOT EXISTS insider_transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  cik TEXT,
  accession TEXT,
  filing_date TEXT,
  transaction_date TEXT,
  owner_name TEXT,
  owner_title TEXT,
  officer_title TEXT,
  transaction_code TEXT NOT NULL,
  transaction_type TEXT NOT NULL,
  shares REAL,
  price REAL,
  dollar_value REAL,
  shares_owned_after REAL,
  security_title TEXT,
  source_url TEXT,
  raw_json TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(ticker, accession, owner_name, transaction_date, transaction_code, shares, price)
);
CREATE INDEX IF NOT EXISTS idx_insider_tx_ticker_date ON insider_transactions(ticker, transaction_date DESC);
CREATE INDEX IF NOT EXISTS idx_insider_tx_code ON insider_transactions(transaction_code);

CREATE TABLE IF NOT EXISTS insider_leads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  evaluated_at TEXT NOT NULL DEFAULT (datetime('now')),
  status TEXT NOT NULL,
  score REAL NOT NULL,
  recommended_use TEXT NOT NULL DEFAULT 'thesis_support_only',
  open_market_buy_count INTEGER NOT NULL DEFAULT 0,
  distinct_buyers INTEGER NOT NULL DEFAULT 0,
  total_buy_value REAL NOT NULL DEFAULT 0,
  role_quality TEXT,
  materiality_label TEXT,
  liquidity_label TEXT,
  risk_flags TEXT,
  positive_factors TEXT,
  evidence_json TEXT NOT NULL,
  notes TEXT,
  UNIQUE(ticker, evaluated_at)
);
CREATE INDEX IF NOT EXISTS idx_insider_leads_ticker_eval ON insider_leads(ticker, evaluated_at DESC);
CREATE INDEX IF NOT EXISTS idx_insider_leads_status_score ON insider_leads(status, score DESC);

CREATE TABLE IF NOT EXISTS suspicious_activity_flags (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_table TEXT NOT NULL,
  source_id TEXT,
  ticker TEXT NOT NULL,
  flag_type TEXT NOT NULL,
  severity TEXT NOT NULL,
  recommended_action TEXT NOT NULL,
  evidence TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_suspicious_flags_ticker ON suspicious_activity_flags(ticker, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_suspicious_flags_source ON suspicious_activity_flags(source_table, source_id);

CREATE TABLE IF NOT EXISTS alpha_search_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  source_job_id TEXT NOT NULL DEFAULT 'wolfy-alpha-search-report',
  agent_run_id TEXT,
  title TEXT NOT NULL,
  market_context TEXT,
  sections_json TEXT NOT NULL,
  summary TEXT NOT NULL,
  delivered_to TEXT,
  raw_payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alpha_reports_created ON alpha_search_reports(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alpha_reports_job ON alpha_search_reports(source_job_id, created_at DESC);

CREATE TABLE IF NOT EXISTS alpha_leads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  report_id INTEGER REFERENCES alpha_search_reports(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  ticker TEXT NOT NULL,
  lead_type TEXT NOT NULL,
  title TEXT NOT NULL,
  thesis TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new',
  evidence_quality_score REAL NOT NULL DEFAULT 0.0,
  evidence_count INTEGER NOT NULL DEFAULT 0,
  highest_source_quality REAL NOT NULL DEFAULT 0.0,
  suspicious_action TEXT NOT NULL DEFAULT 'clear',
  suspicious_flags_json TEXT NOT NULL DEFAULT '[]',
  catalyst_window TEXT,
  social_context TEXT,
  filing_context TEXT,
  insider_context TEXT,
  complete_ticket INTEGER NOT NULL DEFAULT 0,
  recommendation_id INTEGER REFERENCES recommendations(id),
  next_research_question TEXT,
  raw_payload_json TEXT NOT NULL,
  source_fingerprint TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_alpha_leads_ticker_status ON alpha_leads(ticker, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_alpha_leads_quality ON alpha_leads(evidence_quality_score DESC, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_alpha_leads_suspicious ON alpha_leads(suspicious_action, updated_at DESC);

CREATE TABLE IF NOT EXISTS alpha_lead_evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id INTEGER NOT NULL REFERENCES alpha_leads(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  evidence_type TEXT NOT NULL,
  source_title TEXT,
  source_url TEXT,
  source_published_at TEXT,
  quote_or_fact TEXT NOT NULL,
  quality_score REAL NOT NULL DEFAULT 0.5,
  relevance_score REAL NOT NULL DEFAULT 0.5,
  notes TEXT,
  source_fingerprint TEXT NOT NULL,
  UNIQUE(lead_id, source_fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_alpha_evidence_lead ON alpha_lead_evidence(lead_id, quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_alpha_evidence_url ON alpha_lead_evidence(source_url);

CREATE TABLE IF NOT EXISTS alpha_handoffs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id INTEGER REFERENCES alpha_leads(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  target_agent TEXT NOT NULL,
  task_type TEXT NOT NULL,
  title TEXT NOT NULL,
  question TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 50,
  status TEXT NOT NULL DEFAULT 'queued',
  postgres_task_id TEXT,
  source_fingerprint TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_alpha_handoffs_agent_status ON alpha_handoffs(target_agent, status, priority, created_at);

CREATE TABLE IF NOT EXISTS system_metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  captured_at TEXT NOT NULL DEFAULT (datetime('now')),
  hermes_bytes INTEGER,
  wolfy_bytes INTEGER,
  db_bytes INTEGER,
  root_used_pct REAL,
  root_avail_bytes INTEGER,
  cron_job_count INTEGER,
  notes TEXT
);
'''

SOURCES = [
  ('The Intelligent Investor', 'Benjamin Graham', 'book', 'margin of safety, defensive vs enterprising investor', 10),
  ('Security Analysis', 'Benjamin Graham and David Dodd', 'book', 'asset value, earnings power, balance sheet discipline', 15),
  ('Common Stocks and Uncommon Profits', 'Philip Fisher', 'book', 'scuttlebutt, quality growth, management quality', 20),
  ('Berkshire Hathaway Shareholder Letters', 'Warren Buffett / Charlie Munger', 'public_letters', 'https://www.berkshirehathaway.com/letters/letters.html', 10),
  ('One Up on Wall Street', 'Peter Lynch', 'book', 'earnings growth, understandable businesses, category discipline', 30),
  ('The Most Important Thing', 'Howard Marks', 'book', 'cycles, risk, second-level thinking', 25),
  ('How to Make Money in Stocks', "William O'Neil", 'book', 'CAN SLIM, relative strength, earnings + breakouts', 10),
  ('Trade Like a Stock Market Wizard', 'Mark Minervini', 'book', 'trend template, VCP, risk management', 10),
  ('Think and Trade Like a Champion', 'Mark Minervini', 'book', 'execution, position sizing, rules', 15),
  ('Secrets for Profiting in Bull and Bear Markets', 'Stan Weinstein', 'book', 'stage analysis, 30-week MA, sector rotation', 20),
  ('Reminiscences of a Stock Operator', 'Edwin Lefevre / Jesse Livermore', 'book', 'trend, patience, speculation psychology', 35),
  ('Market Wizards', 'Jack Schwager', 'book', 'risk, process, trader mental models', 25),
  ('Expectations Investing', 'Michael Mauboussin / Alfred Rappaport', 'book', 'market-implied expectations, fundamentals vs price', 30),
  ('Damodaran valuation public materials', 'Aswath Damodaran', 'public_course', 'https://pages.stern.nyu.edu/~adamodar/', 25),
  ('Adaptive Markets', 'Andrew Lo', 'book', 'markets evolve, model decay, adaptation', 40),
]

TASKS = [
  ('Build source map and copyright-safe ingestion policy', 'knowledge_base', 'Track public vs user-provided materials and avoid pirated content.', 5),
  ('Extract one high-quality trading/investing framework per hour when tokens allow', 'knowledge_base', 'Create principles, applications, and candidate strategy rules from queued sources.', 10),
  ('Convert notes into Wolfy strategy rules', 'strategy', 'Turn principles into executable filters/scoring/risk constraints.', 10),
  ('Log every actionable recommendation', 'recommendation_tracking', 'Persist ticker, thesis, entry, stop, target, sizing, and confidence.', 5),
  ('Track paper portfolio outcomes', 'recommendation_tracking', 'Mark triggers, stops, targets, R-multiple, days held, drawdown.', 10),
  ('Add earnings/catalyst filter', 'data_pipeline', 'Prevent binary-event trades unless explicitly flagged.', 15),
  ('Add Robinhood tradability proxy/filter', 'data_pipeline', 'Reject names likely unavailable or unsuitable for Robinhood.', 20),
  ('Build weekly performance review', 'evaluation', 'Score Wolfy by setup type, confidence, regime, sector, and R.', 25),
  ('Scan SEC Form 4 insider-buying support signals', 'data_pipeline', 'Find legal public Form 4 open-market buys and persist thesis-support leads; never standalone triggers.', 12),
  ('Monitor storage and database growth', 'operations', 'Capture filesystem and database metrics with scale-up thresholds.', 5),
]

RULES = [
  ('Every actionable idea needs invalidation', 'risk', 'No trade candidate can be actionable unless it includes stop/invalidation and position-size guidance.', 'Wolfy user constraints + risk management canon'),
  ('Do not chase severe extension', 'technical', 'Fresh entries are penalized when price is more than 12% above the 20DMA unless explicitly tagged as high-momentum watch-only.', "O'Neil/Minervini momentum discipline + scanner extension penalty"),
  ('Max three concurrent paper positions', 'portfolio', 'Wolfy paper book may hold at most three active positions.', 'User constraint'),
  ('Prefer liquid U.S. stocks and ETFs', 'universe', 'Avoid thin, low-float, foreign manipulation-risk, or pump-like names unless explicitly approved.', 'User constraint + fraud filter'),
  ('Insider buying is thesis support only', 'alpha', 'SEC Form 4 insider purchases may strengthen conviction only when they are open-market buys, preferably clustered/high-quality roles/material size, and never replace technical setup, fundamentals, liquidity, Robinhood tradability, or Sentinel review.', 'Public SEC Form 4 workflow + Wolfy risk discipline'),
  ('Reject non-open-market insider signals', 'alpha', 'Awards, option exercises/conversions, tax withholding, gifts, and insider selling do not count as bullish insider-buying alpha; microcap/thin/promoted names are vetoed as manipulation-risk unless explicitly approved.', 'SEC Form 4 transaction-code filter + user manipulation-risk constraint'),
  ('Grade every recommendation', 'evaluation', 'Recommendations must be later scored for trigger, target, stop, max adverse/favorable excursion, and R multiple.', 'Model accountability'),
]

def main():
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    now = datetime.now(timezone.utc).isoformat()
    con.execute("INSERT OR REPLACE INTO meta(key,value,updated_at) VALUES('db_created_or_verified',?,?)", (now, now))
    con.execute("INSERT OR REPLACE INTO meta(key,value,updated_at) VALUES('paper_account_start','5000',?)", (now,))
    con.execute("INSERT OR REPLACE INTO meta(key,value,updated_at) VALUES('max_concurrent_positions','3',?)", (now,))
    con.execute("INSERT OR REPLACE INTO meta(key,value,updated_at) VALUES('knowledge_approach','hybrid_public_plus_user_provided',?)", (now,))
    allow = [
      ('command','sqlite3','SQLite CLI for inspecting and maintaining Wolfy DB'),
      ('command','python3','Python runtime for Wolfy scripts'),
      ('path',str(DB),'Wolfy persistent SQLite database'),
      ('path',str(BASE),'Wolfy working directory'),
      ('script','/root/.hermes/wolfy/init_wolfy_db.py','Database initialization'),
      ('script','/root/.hermes/wolfy/wolfy_scanner.py','Free-data scanner'),
      ('script','/root/.hermes/wolfy/wolfy_status.py','Storage and DB health reporting'),
      ('script','/root/.hermes/wolfy/hourly_knowledge_context.py','Hourly knowledge-builder context'),
      ('script','/root/.hermes/wolfy/recommendation_logger.py','Validate and log Wolfy recommendations as pending_review or watchlist-only'),
      ('script','/root/.hermes/wolfy/insider_buying.py','SEC Form 4 insider-buying lead scoring and persistence'),
      ('script','/root/.hermes/wolfy/suspicious_activity.py','Pump/manipulation risk flagging for scanner and recommendation leads'),
      ('script','/root/.hermes/wolfy/alpha_search_pipeline.py','Persistent Alpha Search Report storage, evidence scoring, suspicious flags, and handoffs'),
      ('script','/root/.hermes/wolfy/yang_technical_context.py','Yang technical-analysis context, candidate gating, and Postgres task/run start'),
      ('script','/root/.hermes/wolfy/yang_technical_reviews.py','Yang technical-review persistence helper for entry/exit/ATR/R plans'),
    ]
    con.executemany("INSERT OR IGNORE INTO automation_allowlist(item_type,item,purpose) VALUES(?,?,?)", allow)
    for title, author, source_type, url_or_reference, priority in SOURCES:
        con.execute(
            """
            INSERT INTO knowledge_sources(title,author,source_type,url_or_reference,priority)
            SELECT ?,?,?,?,?
            WHERE NOT EXISTS (
              SELECT 1 FROM knowledge_sources
              WHERE title=? AND IFNULL(author,'')=IFNULL(?,'') AND source_type=?
            )
            """,
            (title, author, source_type, url_or_reference, priority, title, author, source_type),
        )
    con.executemany("""INSERT OR IGNORE INTO training_tasks(task_name,category,objective,priority)
                       VALUES(?,?,?,?)""", TASKS)
    con.executemany("""INSERT OR IGNORE INTO strategy_rules(rule_name,rule_type,description,source_basis,implementation_status,enabled)
                       VALUES(?,?,?,?,?,1)""", [(a,b,c,d,'active') for a,b,c,d in RULES])
    con.commit()
    count_tables = ['knowledge_sources','knowledge_notes','strategy_rules','training_tasks','recommendations','yang_reviews','scanner_runs','system_metrics','automation_allowlist','insider_transactions','insider_leads','suspicious_activity_flags','alpha_search_reports','alpha_leads','alpha_lead_evidence','alpha_handoffs']
    counts = {name: con.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0] for name in count_tables}
    con.close()
    print(f'Wolfy DB initialized: {DB}')
    for k,v in counts.items():
        print(f'{k}: {v}')

if __name__ == '__main__':
    main()
