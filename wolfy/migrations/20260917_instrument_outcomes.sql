-- Separate underlying setup quality from exact-option expression outcomes.
-- Existing recommendation_outcomes remain the canonical underlying ledger.
BEGIN;

ALTER TABLE recommendation_outcomes
  ADD COLUMN IF NOT EXISTS outcome_type text NOT NULL DEFAULT 'underlying_setup';

DO $$
DECLARE duplicate_row record;
BEGIN
  SELECT paper_trade_id, count(*) AS row_count
    INTO duplicate_row
    FROM recommendation_outcomes
   WHERE paper_trade_id IS NOT NULL
   GROUP BY paper_trade_id
  HAVING count(*) > 1
   ORDER BY paper_trade_id
   LIMIT 1;
  IF FOUND THEN
    RAISE EXCEPTION
      'instrument outcomes migration aborted: paper trade % has % underlying outcomes',
      duplicate_row.paper_trade_id, duplicate_row.row_count;
  END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_underlying_outcome_paper_trade
  ON recommendation_outcomes(paper_trade_id)
  WHERE paper_trade_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS option_outcomes (
  id bigserial PRIMARY KEY,
  recommendation_id text NOT NULL,
  paper_trade_id text NOT NULL,
  option_evaluation_id bigint NOT NULL REFERENCES option_structure_evaluations(id),
  entry_snapshot_id text NOT NULL REFERENCES option_chain_snapshots(snapshot_id),
  exit_snapshot_id text REFERENCES option_chain_snapshots(snapshot_id),
  expression text NOT NULL CHECK (expression IN ('long_call', 'call_debit_spread')),
  status text NOT NULL CHECK (status = 'closed'),
  exit_reason text NOT NULL CHECK (btrim(exit_reason) <> ''),
  expiration date NOT NULL,
  entry_value numeric NOT NULL CHECK (
    entry_value NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)
    AND entry_value >= 0
  ),
  exit_value numeric NOT NULL CHECK (
    exit_value NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)
    AND exit_value >= 0
  ),
  max_loss numeric NOT NULL CHECK (
    max_loss NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)
    AND max_loss > 0
  ),
  pnl numeric NOT NULL CHECK (
    pnl NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)
    AND pnl >= -max_loss
  ),
  return_on_risk numeric NOT NULL CHECK (
    return_on_risk NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)
  ),
  quote_at timestamptz,
  notes jsonb NOT NULL CHECK (jsonb_typeof(notes) = 'object'),
  paper_only boolean NOT NULL DEFAULT true CHECK (paper_only),
  no_live_execution boolean NOT NULL DEFAULT true CHECK (no_live_execution),
  broker_order_submitted boolean NOT NULL DEFAULT false CHECK (NOT broker_order_submitted),
  graded_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (paper_trade_id)
);
CREATE INDEX IF NOT EXISTS idx_option_outcomes_recommendation
  ON option_outcomes(recommendation_id, graded_at DESC);
CREATE INDEX IF NOT EXISTS idx_option_outcomes_evaluation
  ON option_outcomes(option_evaluation_id);

COMMIT;
