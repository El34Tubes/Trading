-- Versioned setup reasons and immutable common setup candidates.
BEGIN;

ALTER TABLE setup_gate_evaluations
    DROP CONSTRAINT IF EXISTS setup_gate_evaluations_reason_code_version_check;
ALTER TABLE setup_gate_evaluations
    ADD CONSTRAINT setup_gate_evaluations_reason_code_version_check
    CHECK (reason_code_version IN (1, 2));

CREATE OR REPLACE FUNCTION wolfy_validate_setup_gate_evaluation()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v1_reasons CONSTANT TEXT[] := ARRAY[
        'passed', 'missing_current_price', 'missing_current_features',
        'insufficient_history', 'security_ineligible', 'liquidity_failed',
        'market_regime_failed', 'trend_failed', 'breakout_not_confirmed',
        'pullback_shape_failed', 'relative_strength_failed', 'volume_failed',
        'stop_risk_too_wide', 'overextended', 'breadth_unavailable',
        'breadth_failed', 'sector_confirmation_failed', 'event_landmine',
        'option_chain_missing', 'option_liquidity_failed',
        'portfolio_correlation_block', 'daily_limit_block'
    ]::TEXT[];
    v2_reasons CONSTANT TEXT[] := v1_reasons || ARRAY[
        'feature_stale', 'range_expansion_failed', 'reclaim_not_confirmed',
        'volatility_contraction_failed'
    ]::TEXT[];
    allowed_reasons TEXT[];
    sorted_reasons TEXT[];
BEGIN
    allowed_reasons := CASE NEW.reason_code_version
        WHEN 1 THEN v1_reasons WHEN 2 THEN v2_reasons ELSE ARRAY[]::TEXT[] END;
    SELECT array_agg(reason ORDER BY reason)
      INTO sorted_reasons FROM unnest(NEW.reason_codes) AS reason;
    IF NEW.reason_code_version NOT IN (1, 2)
       OR cardinality(NEW.reason_codes) = 0
       OR NOT NEW.reason_codes <@ allowed_reasons
       OR NEW.reason_codes <> sorted_reasons
       OR cardinality(NEW.reason_codes) <> (
           SELECT count(DISTINCT reason) FROM unnest(NEW.reason_codes) AS reason
       )
       OR (NEW.passed AND NEW.reason_codes <> ARRAY['passed']::TEXT[])
       OR (NOT NEW.passed AND 'passed' = ANY(NEW.reason_codes))
       OR NEW.terminal_reason <> ALL(NEW.reason_codes)
       OR (NEW.passed AND NEW.terminal_reason <> 'passed')
       OR jsonb_typeof(NEW.failed_gates) <> 'array'
       OR (NEW.passed AND NEW.failed_gates <> '[]'::jsonb)
       OR (NOT NEW.passed AND NEW.failed_gates <> to_jsonb(NEW.reason_codes))
       OR jsonb_typeof(NEW.gate_facts) <> 'object'
       OR jsonb_typeof(NEW.metrics) <> 'object'
       OR jsonb_typeof(NEW.provenance) <> 'object'
       OR NOT wolfy_is_canonical_ledger_text(NEW.source_fingerprint)
       OR NOT wolfy_is_canonical_ledger_text(NEW.ticker)
       OR NEW.ticker <> upper(NEW.ticker)
       OR NOT wolfy_is_canonical_ledger_text(NEW.strategy)
    THEN
        RAISE EXCEPTION 'noncanonical setup gate evaluation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TABLE IF NOT EXISTS setup_candidates (
    candidate_id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES daily_evaluation_runs(id),
    universe_snapshot_id UUID NOT NULL REFERENCES recommendation_universe_snapshots(snapshot_id),
    gate_evaluation_id BIGINT NOT NULL UNIQUE REFERENCES setup_gate_evaluations(id),
    ticker TEXT NOT NULL CHECK (wolfy_is_canonical_ledger_text(ticker) AND ticker = upper(ticker)),
    strategy_id TEXT NOT NULL CHECK (wolfy_is_canonical_ledger_text(strategy_id)),
    strategy_version TEXT NOT NULL CHECK (wolfy_is_canonical_ledger_text(strategy_version)),
    sector TEXT NOT NULL CHECK (wolfy_is_canonical_ledger_text(sector)),
    score NUMERIC NOT NULL CHECK (
        score NOT IN ('NaN'::NUMERIC, 'Infinity'::NUMERIC, '-Infinity'::NUMERIC)
    ),
    score_components JSONB NOT NULL CHECK (
        jsonb_typeof(score_components) = 'object' AND score_components <> '{}'::jsonb
    ),
    entry NUMERIC NOT NULL CHECK (
        entry NOT IN ('NaN'::NUMERIC, 'Infinity'::NUMERIC, '-Infinity'::NUMERIC)
        AND entry > 0
    ),
    stop NUMERIC NOT NULL CHECK (
        stop NOT IN ('NaN'::NUMERIC, 'Infinity'::NUMERIC, '-Infinity'::NUMERIC)
        AND stop > 0 AND stop < entry
    ),
    target NUMERIC NOT NULL CHECK (
        target NOT IN ('NaN'::NUMERIC, 'Infinity'::NUMERIC, '-Infinity'::NUMERIC)
        AND target > entry
    ),
    facts_hash TEXT NOT NULL CHECK (facts_hash ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, ticker, strategy_id, strategy_version),
    FOREIGN KEY (universe_snapshot_id, ticker)
        REFERENCES recommendation_universe_members(snapshot_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_setup_candidates_run_score
    ON setup_candidates(run_id, score DESC, ticker, strategy_id);

CREATE OR REPLACE FUNCTION wolfy_validate_setup_candidate_binding()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    run_snapshot TEXT;
    gate_row setup_gate_evaluations%ROWTYPE;
    member_row recommendation_universe_members%ROWTYPE;
    component_sum NUMERIC;
BEGIN
    SELECT universe_snapshot_id INTO run_snapshot
      FROM daily_evaluation_runs WHERE id = NEW.run_id;
    SELECT * INTO gate_row FROM setup_gate_evaluations WHERE id = NEW.gate_evaluation_id;
    SELECT * INTO member_row FROM recommendation_universe_members
     WHERE snapshot_id = NEW.universe_snapshot_id AND ticker = NEW.ticker;
    SELECT sum((value #>> '{}')::NUMERIC) INTO component_sum
      FROM jsonb_each(NEW.score_components);
    IF run_snapshot IS DISTINCT FROM NEW.universe_snapshot_id::TEXT
       OR gate_row.id IS NULL OR gate_row.run_id <> NEW.run_id
       OR gate_row.ticker <> NEW.ticker OR gate_row.strategy <> NEW.strategy_id
       OR NOT gate_row.passed
       OR member_row.ticker IS NULL OR NOT member_row.included
       OR member_row.sector <> NEW.sector
       OR component_sum IS DISTINCT FROM NEW.score
       OR EXISTS (
           SELECT 1 FROM jsonb_each(NEW.score_components) AS component
            WHERE jsonb_typeof(component.value) <> 'string'
               OR component.value #>> '{}' !~ '^-?(0|[1-9][0-9]*)([.][0-9]+)?$'
               OR (component.value #>> '{}')::NUMERIC IN (
                   'NaN'::NUMERIC, 'Infinity'::NUMERIC, '-Infinity'::NUMERIC
               )
       )
    THEN
        RAISE EXCEPTION 'setup candidate binding is noncanonical';
    END IF;
    RETURN NEW;
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
    RAISE EXCEPTION 'setup candidate score components are nonnumeric or nonfinite';
END;
$$;
DROP TRIGGER IF EXISTS trg_validate_setup_candidate_binding ON setup_candidates;
CREATE TRIGGER trg_validate_setup_candidate_binding
    BEFORE INSERT OR UPDATE ON setup_candidates
    FOR EACH ROW EXECUTE FUNCTION wolfy_validate_setup_candidate_binding();

CREATE OR REPLACE FUNCTION wolfy_reject_setup_candidate_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'setup candidates are immutable';
END;
$$;
DROP TRIGGER IF EXISTS trg_setup_candidates_immutable ON setup_candidates;
CREATE TRIGGER trg_setup_candidates_immutable
    BEFORE UPDATE OR DELETE ON setup_candidates
    FOR EACH ROW EXECUTE FUNCTION wolfy_reject_setup_candidate_mutation();

COMMIT;
