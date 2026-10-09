-- Bind every option evaluation to an immutable, ticker-specific chain snapshot.
-- This migration deliberately aborts when legacy evaluations cannot supply the
-- original decision time; provenance is never synthesized during upgrade.
BEGIN;

CREATE TABLE IF NOT EXISTS option_chain_snapshots (
  snapshot_id text PRIMARY KEY,
  ticker text NOT NULL,
  provider text NOT NULL,
  source_url text NOT NULL,
  fetched_at timestamptz NOT NULL,
  market_at timestamptz NOT NULL,
  available_at timestamptz NOT NULL,
  payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
  chain jsonb NOT NULL CHECK (jsonb_typeof(chain) = 'array'),
  paper_only boolean NOT NULL DEFAULT true CHECK (paper_only),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (market_at <= fetched_at),
  CHECK (fetched_at <= available_at)
);
ALTER TABLE option_chain_snapshots
  DROP CONSTRAINT IF EXISTS option_chain_snapshots_ticker_payload_sha256_key;

CREATE OR REPLACE FUNCTION wolfy_reject_option_snapshot_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'option chain snapshots are append-only';
END
$$;
DROP TRIGGER IF EXISTS trg_option_chain_snapshots_immutable ON option_chain_snapshots;
CREATE TRIGGER trg_option_chain_snapshots_immutable
  BEFORE UPDATE OR DELETE ON option_chain_snapshots
  FOR EACH ROW EXECUTE FUNCTION wolfy_reject_option_snapshot_mutation();

ALTER TABLE option_structure_evaluations
  ADD COLUMN IF NOT EXISTS snapshot_id text REFERENCES option_chain_snapshots(snapshot_id),
  ADD COLUMN IF NOT EXISTS decision_at timestamptz,
  ADD COLUMN IF NOT EXISTS source_signal_id bigint,
  ADD COLUMN IF NOT EXISTS run_id bigint;

DO $$
DECLARE
  unresolved record;
BEGIN
  SELECT id,ticker,signal_dt,strategy_name
    INTO unresolved
    FROM option_structure_evaluations
   WHERE snapshot_id IS NULL OR decision_at IS NULL
   ORDER BY id
   LIMIT 1;
  IF FOUND THEN
    RAISE EXCEPTION
      'option snapshot provenance migration aborted: evaluation id %, ticker %, signal_dt %, strategy % lacks defensible snapshot/decision provenance',
      unresolved.id, unresolved.ticker, unresolved.signal_dt, unresolved.strategy_name;
  END IF;
END
$$;

ALTER TABLE option_structure_evaluations
  ALTER COLUMN snapshot_id SET NOT NULL,
  ALTER COLUMN decision_at SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_option_structure_evaluations_snapshot
  ON option_structure_evaluations(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_option_chain_snapshots_ticker_available
  ON option_chain_snapshots(ticker, available_at DESC);

COMMIT;
