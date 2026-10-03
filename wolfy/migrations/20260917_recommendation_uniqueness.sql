-- Install paper-recommendation identities as reviewed schema, never runtime DDL.
-- Active duplicates are reported and left untouched for explicit human review.
BEGIN;

SELECT pg_advisory_xact_lock(
  hashtextextended('wolfy_recommendation_uniqueness_migration_v1', 0)
);
LOCK TABLE recommendations IN SHARE ROW EXCLUSIVE MODE;

DO $$
DECLARE
  duplicate_keys jsonb;
BEGIN
  SELECT jsonb_agg(
           jsonb_build_object(
             'ticker', ticker,
             'signal_dt', signal_dt,
             'strategy_name', strategy_name,
             'row_count', row_count,
             'recommendation_ids', recommendation_ids
           )
           ORDER BY ticker, signal_dt, strategy_name
         )
    INTO duplicate_keys
    FROM (
      SELECT ticker,
             notes->>'signal_dt' AS signal_dt,
             notes->>'strategy_name' AS strategy_name,
             count(*) AS row_count,
             jsonb_agg(id ORDER BY id) AS recommendation_ids
        FROM recommendations
       WHERE status IN ('paper_candidate', 'paper_logged')
         AND notes->>'signal_dt' IS NOT NULL
         AND notes->>'strategy_name' IS NOT NULL
       GROUP BY ticker, notes->>'signal_dt', notes->>'strategy_name'
      HAVING count(*) > 1
    ) duplicates;

  IF duplicate_keys IS NOT NULL THEN
    RAISE EXCEPTION
      'duplicate active recommendation identities block migration: %',
      duplicate_keys;
  END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_experimental_paper_recommendation_signal
  ON recommendations (
    ticker,
    (notes->>'signal_dt'),
    (notes->>'strategy_name')
  )
  WHERE recommendation_type = 'experimental_defined_risk_option'
    AND status IN ('paper_candidate', 'paper_logged')
    AND notes->>'signal_dt' IS NOT NULL
    AND notes->>'strategy_name' IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_recommendation_signal
  ON recommendations (
    ticker,
    (notes->>'signal_dt'),
    (notes->>'strategy_name')
  )
  WHERE status IN ('paper_candidate', 'paper_logged')
    AND notes->>'signal_dt' IS NOT NULL
    AND notes->>'strategy_name' IS NOT NULL;

COMMIT;
