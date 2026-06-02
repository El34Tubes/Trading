-- Wolfy / Hermes-EOD Section 6 non-destructive Postgres migration
-- Source: /root/.hermes/cache/documents/doc_26a12d1486bd_hermes_bootstrap.md
-- Safety: CREATE TABLE IF NOT EXISTS, CREATE INDEX IF NOT EXISTS, UPSERT-only seeds.
-- No destructive DDL/DML. Strategy seeds are research_only only; human approval is required for capital use.

BEGIN;

CREATE TABLE IF NOT EXISTS eod_schema_migrations (
  name text PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now(),
  notes text
);

CREATE TABLE IF NOT EXISTS config (
  key text PRIMARY KEY,
  value jsonb NOT NULL,
  updated_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS prices (
  ticker text NOT NULL,
  dt date NOT NULL,
  open numeric,
  high numeric,
  low numeric,
  close numeric,
  volume bigint,
  PRIMARY KEY (ticker, dt)
);
CREATE INDEX IF NOT EXISTS idx_prices_dt ON prices(dt, ticker);

CREATE TABLE IF NOT EXISTS fundamentals (
  ticker text NOT NULL,
  period date NOT NULL,
  filed date,
  metric text NOT NULL,
  value numeric,
  source text,
  PRIMARY KEY (ticker, period, metric)
);
CREATE INDEX IF NOT EXISTS idx_fundamentals_metric_period ON fundamentals(metric, period DESC);

CREATE TABLE IF NOT EXISTS earnings_calendar (
  ticker text NOT NULL,
  event_dt date NOT NULL,
  session text,
  confirmed boolean,
  PRIMARY KEY (ticker, event_dt),
  CONSTRAINT earnings_calendar_session_check CHECK (session IS NULL OR session IN ('bmo', 'amc'))
);
CREATE INDEX IF NOT EXISTS idx_earnings_calendar_event_dt ON earnings_calendar(event_dt, ticker);

CREATE TABLE IF NOT EXISTS features (
  ticker text NOT NULL,
  dt date NOT NULL,
  sma_fast numeric,
  sma_slow numeric,
  vol_ratio numeric,
  dollar_vol numeric,
  atr numeric,
  vol_regime text,
  PRIMARY KEY (ticker, dt)
);
CREATE INDEX IF NOT EXISTS idx_features_dt_liquidity ON features(dt, dollar_vol DESC);
CREATE INDEX IF NOT EXISTS idx_features_vol_regime ON features(vol_regime, dt DESC);

CREATE TABLE IF NOT EXISTS strategies (
  id serial PRIMARY KEY,
  name text UNIQUE,
  setup_type text,
  status text CHECK (status IN ('research_only','candidate','approved','retired')),
  latest_oos_sharpe numeric,
  latest_oos_verdict boolean,
  last_validated date,
  params jsonb,
  notes text
);
CREATE INDEX IF NOT EXISTS idx_strategies_status ON strategies(status, setup_type);

CREATE TABLE IF NOT EXISTS signals (
  ticker text NOT NULL,
  dt date NOT NULL,
  strategy_id int REFERENCES strategies(id),
  direction text,
  raw jsonb,
  PRIMARY KEY (ticker, dt, strategy_id)
);
CREATE INDEX IF NOT EXISTS idx_signals_dt_strategy ON signals(dt, strategy_id);

CREATE TABLE IF NOT EXISTS setups (
  id serial PRIMARY KEY,
  created_dt date,
  for_session date,
  ticker text,
  strategy_id int REFERENCES strategies(id),
  direction text,
  liquidity_ok boolean,
  event_flag text,
  option_structure jsonb,
  iv_view jsonb,
  size jsonb,
  invalidation numeric,
  thesis text,
  falsification text,
  confidence numeric,
  rank int,
  status text DEFAULT 'proposed',
  CONSTRAINT setups_status_check CHECK (status IN ('proposed','pending_review','taken','skipped','expired','rejected'))
);
CREATE INDEX IF NOT EXISTS idx_setups_for_session_status ON setups(for_session, status, rank);
CREATE INDEX IF NOT EXISTS idx_setups_ticker_created ON setups(ticker, created_dt DESC);

CREATE TABLE IF NOT EXISTS backtests (
  id serial PRIMARY KEY,
  strategy_id int REFERENCES strategies(id),
  run_at timestamptz DEFAULT now(),
  window_start date,
  window_end date,
  is_sharpe numeric,
  oos_sharpe numeric,
  oos_cagr numeric,
  max_dd numeric,
  turnover numeric,
  survives_oos boolean,
  params jsonb,
  report jsonb
);
CREATE INDEX IF NOT EXISTS idx_backtests_strategy_run_at ON backtests(strategy_id, run_at DESC);

CREATE TABLE IF NOT EXISTS research_log (
  id serial PRIMARY KEY,
  ts timestamptz DEFAULT now(),
  hypothesis text,
  rationale text,
  backtest_id int REFERENCES backtests(id),
  outcome text,
  promoted boolean DEFAULT false
);
CREATE INDEX IF NOT EXISTS idx_research_log_ts ON research_log(ts DESC);

CREATE TABLE IF NOT EXISTS positions (
  id serial PRIMARY KEY,
  ticker text,
  opened date,
  structure jsonb,
  risk_amount numeric,
  invalidation numeric,
  status text
);
CREATE INDEX IF NOT EXISTS idx_positions_status_ticker ON positions(status, ticker);

CREATE TABLE IF NOT EXISTS trades (
  id serial PRIMARY KEY,
  position_id int REFERENCES positions(id),
  dt date,
  action text,
  price numeric,
  qty numeric,
  fees numeric
);
CREATE INDEX IF NOT EXISTS idx_trades_position_dt ON trades(position_id, dt);

CREATE TABLE IF NOT EXISTS runs (
  id serial PRIMARY KEY,
  job text,
  started timestamptz,
  finished timestamptz,
  status text,
  detail jsonb
);
CREATE INDEX IF NOT EXISTS idx_runs_job_started ON runs(job, started DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status_started ON runs(status, started DESC);

INSERT INTO config(key, value) VALUES
  ('min_dollar_vol', '{"usd": 25000000, "note": "EOD universe liquidity floor; tune upward before capital use."}'::jsonb),
  ('slippage_bps', '{"bps": 10, "direction": "may_only_increase_for_backtests_without_human_review"}'::jsonb),
  ('risk_per_trade', '{"fraction_of_equity": 0.01, "paper_account_usd": 5000}'::jsonb),
  ('max_portfolio_heat', '{"fraction_of_equity": 0.03, "max_concurrent_positions": 3}'::jsonb),
  ('max_name_weight', '{"fraction_of_equity": 0.20}'::jsonb),
  ('max_drawdown_killswitch', '{"fraction_of_equity": 0.10, "action": "stop_new_risk_and_notify"}'::jsonb),
  ('max_adv_frac', '{"fraction_of_average_daily_volume": 0.02}'::jsonb)
ON CONFLICT (key) DO UPDATE
SET value = EXCLUDED.value,
    updated_at = now();

INSERT INTO strategies(name, setup_type, status, params, notes) VALUES
  ('pead', 'post_earnings_announcement_drift', 'research_only', '{"source": "Hermes-EOD Section 3", "requires_backtest": true}'::jsonb, 'Seeded as research_only. Must pass walk-forward OOS and human approval before capital setups.'),
  ('trend_volume_vol_regime', 'trend_plus_volume_confirmation', 'research_only', '{"source": "Hermes-EOD Section 3", "requires_volatility_regime_filter": true, "requires_backtest": true}'::jsonb, 'Seeded as research_only. Deterministic features/signals required; no LLM-generated edge.'),
  ('sector_cross_sectional_momentum', 'cross_sectional_momentum', 'research_only', '{"source": "Hermes-EOD Section 3", "rebalance": "weekly", "requires_backtest": true}'::jsonb, 'Seeded as research_only. Human approval required for status promotion beyond candidate.')
ON CONFLICT (name) DO UPDATE
SET setup_type = EXCLUDED.setup_type,
    params = EXCLUDED.params,
    notes = EXCLUDED.notes;

INSERT INTO eod_schema_migrations(name, notes) VALUES
  ('20260601_eod_section6_schema', 'Created Hermes-EOD Section 6 tables and research_only seeds non-destructively.')
ON CONFLICT (name) DO UPDATE
SET applied_at = now(),
    notes = EXCLUDED.notes;

COMMIT;
