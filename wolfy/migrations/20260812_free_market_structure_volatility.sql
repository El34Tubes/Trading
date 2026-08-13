-- Wolfy free market-structure and options-volatility research schema.
-- Non-destructive. No paid sources, broker writes, strategy approval, or live execution.
BEGIN;

CREATE TABLE IF NOT EXISTS technical_market_series (
  series text NOT NULL,
  observation_date date NOT NULL,
  available_at timestamptz NOT NULL,
  value numeric,
  open numeric,
  high numeric,
  low numeric,
  source text NOT NULL,
  source_url text,
  license_class text NOT NULL DEFAULT 'free_public_terms_apply',
  ingested_at timestamptz NOT NULL DEFAULT now(),
  raw jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY(series, observation_date)
);
CREATE INDEX IF NOT EXISTS idx_technical_market_series_available ON technical_market_series(series, available_at DESC);

CREATE TABLE IF NOT EXISTS finra_short_volume (
  ticker text NOT NULL,
  observation_date date NOT NULL,
  available_at timestamptz NOT NULL,
  short_volume numeric,
  short_exempt_volume numeric,
  total_volume numeric,
  short_fraction numeric,
  short_exempt_fraction numeric,
  market text,
  scope text NOT NULL,
  source text NOT NULL,
  source_url text,
  ingested_at timestamptz NOT NULL DEFAULT now(),
  raw jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY(ticker, observation_date)
);
CREATE INDEX IF NOT EXISTS idx_finra_short_volume_available ON finra_short_volume(observation_date, available_at, ticker);

CREATE TABLE IF NOT EXISTS nasdaq_short_interest (
  ticker text NOT NULL,
  settlement_date date NOT NULL,
  available_at timestamptz NOT NULL,
  short_interest numeric,
  average_daily_share_volume numeric,
  days_to_cover numeric,
  source text NOT NULL,
  source_url text,
  ingested_at timestamptz NOT NULL DEFAULT now(),
  raw jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY(ticker, settlement_date)
);
CREATE INDEX IF NOT EXISTS idx_nasdaq_short_interest_available ON nasdaq_short_interest(ticker, available_at DESC);

CREATE TABLE IF NOT EXISTS universe_membership_snapshots (
  dt date NOT NULL,
  symbol text NOT NULL,
  eligible boolean NOT NULL,
  sector text,
  source text NOT NULL,
  snapshot_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(dt, symbol, source)
);
CREATE INDEX IF NOT EXISTS idx_universe_membership_snapshot_dt ON universe_membership_snapshots(dt, eligible, symbol);

CREATE TABLE IF NOT EXISTS options_technical_features (
  ticker text NOT NULL,
  dt date NOT NULL,
  atr_pct numeric,
  realized_vol_annualized numeric,
  pre_breakout_contraction_ratio numeric,
  range_expansion_ratio numeric,
  close_location_value numeric,
  upper_wick_ratio numeric,
  volume_percentile numeric,
  options_volatility_setup boolean NOT NULL,
  high_volatility_allowed boolean NOT NULL DEFAULT true,
  transformation_version text NOT NULL DEFAULT 'options-vol-v1',
  PRIMARY KEY(ticker, dt)
);

CREATE TABLE IF NOT EXISTS market_breadth (
  dt date PRIMARY KEY,
  eligible_count integer NOT NULL,
  advancers integer,
  decliners integer,
  advance_decline_ratio numeric,
  pct_above_20dma numeric,
  pct_above_50dma numeric,
  pct_above_200dma numeric,
  new_20d_high_fraction numeric,
  new_20d_low_fraction numeric,
  up_volume_fraction numeric,
  universe_definition text NOT NULL,
  transformation_version text NOT NULL DEFAULT 'breadth-v1',
  ingested_at timestamptz NOT NULL DEFAULT now()
);

COMMIT;
