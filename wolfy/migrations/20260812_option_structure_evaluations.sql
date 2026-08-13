-- Forward-only option chain and deterministic structure evaluation audit ledger.
-- Research/paper only; this schema provides no broker-order capability.
BEGIN;

CREATE TABLE IF NOT EXISTS option_structure_evaluations (
  id bigserial PRIMARY KEY,
  ticker text NOT NULL,
  signal_dt date NOT NULL,
  strategy_name text NOT NULL,
  underlying_price numeric NOT NULL,
  technical_target numeric NOT NULL,
  fetched_at timestamptz NOT NULL,
  source text NOT NULL,
  chain jsonb NOT NULL,
  evaluation jsonb NOT NULL,
  selected_structure text,
  paper_only boolean NOT NULL DEFAULT true,
  no_live_execution boolean NOT NULL DEFAULT true,
  broker_order_submitted boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(ticker, signal_dt, strategy_name)
);
CREATE INDEX IF NOT EXISTS idx_option_structure_evaluations_signal
  ON option_structure_evaluations(signal_dt DESC, ticker);

COMMIT;
