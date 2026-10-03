BEGIN;
SELECT pg_advisory_xact_lock(hashtextextended('wolfy_task3_migration', 0));

-- Canonical ledger text strips only ASCII C0 controls (U+0000..U+001F),
-- ordinary space (U+0020), and DEL (U+007F) from both edges. PostgreSQL text
-- cannot contain U+0000. Unicode whitespace is intentionally not normalized.
CREATE OR REPLACE FUNCTION wolfy_is_canonical_ledger_text(value TEXT)
RETURNS BOOLEAN
LANGUAGE SQL
IMMUTABLE STRICT PARALLEL SAFE
AS $$
    SELECT value <> ''
       AND value !~ E'^[\\x01-\\x20\\x7f]|[\\x01-\\x20\\x7f]$'
$$;

-- Match Python json.dumps(..., sort_keys=True, separators=(',', ':')) exactly,
-- including ensure_ascii=True escaping for non-ASCII identity values.
CREATE OR REPLACE FUNCTION wolfy_python_json_string(value TEXT)
RETURNS TEXT
LANGUAGE plpgsql
IMMUTABLE STRICT PARALLEL SAFE
AS $$
DECLARE
    result TEXT := '"';
    character TEXT;
    codepoint INTEGER;
    surrogate INTEGER;
BEGIN
    FOR position IN 1..char_length(value) LOOP
        character := substr(value, position, 1);
        codepoint := ascii(character);
        IF codepoint = 34 THEN
            result := result || E'\\"';
        ELSIF codepoint = 92 THEN
            result := result || E'\\\\';
        ELSIF codepoint = 8 THEN
            result := result || E'\\b';
        ELSIF codepoint = 9 THEN
            result := result || E'\\t';
        ELSIF codepoint = 10 THEN
            result := result || E'\\n';
        ELSIF codepoint = 12 THEN
            result := result || E'\\f';
        ELSIF codepoint = 13 THEN
            result := result || E'\\r';
        ELSIF codepoint < 32 OR (codepoint BETWEEN 127 AND 65535) THEN
            result := result || E'\\u' || lpad(to_hex(codepoint), 4, '0');
        ELSIF codepoint > 65535 THEN
            surrogate := codepoint - 65536;
            result := result
                || E'\\u' || lpad(to_hex(55296 + (surrogate / 1024)), 4, '0')
                || E'\\u' || lpad(to_hex(56320 + (surrogate % 1024)), 4, '0');
        ELSE
            result := result || character;
        END IF;
    END LOOP;
    RETURN result || '"';
END;
$$;

CREATE OR REPLACE FUNCTION wolfy_daily_run_identity(
    target_session DATE,
    evaluator_name TEXT,
    evaluator_version TEXT,
    universe_snapshot_id TEXT
)
RETURNS TEXT
LANGUAGE SQL
IMMUTABLE STRICT PARALLEL SAFE
AS $$
    SELECT encode(
        sha256(convert_to(
            '{"evaluator_name":' || wolfy_python_json_string(evaluator_name)
            || ',"evaluator_version":' || wolfy_python_json_string(evaluator_version)
            || ',"target_session":"'
            || lpad(extract(year FROM target_session)::INTEGER::TEXT, 4, '0') || '-'
            || lpad(extract(month FROM target_session)::INTEGER::TEXT, 2, '0') || '-'
            || lpad(extract(day FROM target_session)::INTEGER::TEXT, 2, '0') || '"'
            || ',"universe_snapshot_id":'
            || wolfy_python_json_string(universe_snapshot_id) || '}',
            'UTF8'
        )),
        'hex'
    )
$$;

-- Validate every populated derived stage independently of run lifecycle status.
-- Empty metadata is valid until stages are recorded; every present top-level key
-- must name one of the immutable required stages and carry the exact Python
-- DerivedStageMetadata persistence shape.
CREATE OR REPLACE FUNCTION wolfy_is_valid_derived_stage_metadata(
    metadata JSONB,
    required_stage_names TEXT[],
    target_session DATE,
    parent_universe_snapshot_id TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
IMMUTABLE STRICT PARALLEL SAFE
AS $$
DECLARE
    stage_name TEXT;
    stage_data JSONB;
    computed_at TIMESTAMPTZ;
    available_at TIMESTAMPTZ;
    source_total INTEGER;
    source_distinct INTEGER;
    source_bad INTEGER;
    source_original JSONB;
    source_sorted JSONB;
BEGIN
    IF jsonb_typeof(metadata) IS DISTINCT FROM 'object'
       OR cardinality(required_stage_names) = 0
       OR EXISTS (
           SELECT 1 FROM unnest(required_stage_names) AS required_stage(value)
           WHERE required_stage.value IS NULL
              OR NOT wolfy_is_canonical_ledger_text(required_stage.value)
       )
       OR required_stage_names IS DISTINCT FROM (
           SELECT array_agg(required_stage.value ORDER BY required_stage.value)
           FROM unnest(required_stage_names) AS required_stage(value)
       )
       OR cardinality(required_stage_names) <> (
           SELECT count(DISTINCT required_stage.value)
           FROM unnest(required_stage_names) AS required_stage(value)
       )
    THEN
        RETURN FALSE;
    END IF;

    FOR stage_name, stage_data IN SELECT key, value FROM jsonb_each(metadata) LOOP
        IF NOT wolfy_is_canonical_ledger_text(stage_name)
           OR NOT stage_name = ANY(required_stage_names)
           OR jsonb_typeof(stage_data) IS DISTINCT FROM 'object'
           OR (SELECT count(*) FROM jsonb_object_keys(stage_data)) <> 8
           OR NOT stage_data ?& ARRAY[
               'input_session', 'computed_at', 'available_at',
               'transformation_version', 'source_run_ids', 'input_hash',
               'universe_snapshot_id', 'provenance'
           ]
           OR jsonb_typeof(stage_data->'input_session') IS DISTINCT FROM 'string'
           OR jsonb_typeof(stage_data->'computed_at') IS DISTINCT FROM 'string'
           OR jsonb_typeof(stage_data->'available_at') IS DISTINCT FROM 'string'
           OR jsonb_typeof(stage_data->'transformation_version') IS DISTINCT FROM 'string'
           OR jsonb_typeof(stage_data->'source_run_ids') IS DISTINCT FROM 'array'
           OR jsonb_typeof(stage_data->'input_hash') IS DISTINCT FROM 'string'
           OR jsonb_typeof(stage_data->'universe_snapshot_id') IS DISTINCT FROM 'string'
           OR jsonb_typeof(stage_data->'provenance') IS DISTINCT FROM 'object'
           OR stage_data->>'input_session' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
           OR (stage_data->>'input_session')::DATE IS DISTINCT FROM target_session
           OR stage_data->>'computed_at' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]+)?(Z|[+]00:00)$'
           OR stage_data->>'available_at' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]+)?(Z|[+]00:00)$'
           OR NOT wolfy_is_canonical_ledger_text(stage_data->>'transformation_version')
           OR jsonb_array_length(stage_data->'source_run_ids') = 0
           OR stage_data->>'input_hash' !~ '^[0-9a-f]{64}$'
           OR NOT wolfy_is_canonical_ledger_text(stage_data->>'universe_snapshot_id')
           OR stage_data->>'universe_snapshot_id' IS DISTINCT FROM parent_universe_snapshot_id
        THEN
            RETURN FALSE;
        END IF;

        computed_at := (stage_data->>'computed_at')::TIMESTAMPTZ;
        available_at := (stage_data->>'available_at')::TIMESTAMPTZ;
        IF available_at < computed_at THEN
            RETURN FALSE;
        END IF;

        SELECT count(*), count(DISTINCT source_id), count(*) FILTER (
                   WHERE jsonb_typeof(source_value) IS DISTINCT FROM 'string'
                      OR NOT wolfy_is_canonical_ledger_text(source_id)
               ),
               jsonb_agg(source_value ORDER BY ordinal),
               jsonb_agg(source_value ORDER BY source_id)
        INTO source_total, source_distinct, source_bad, source_original, source_sorted
        FROM (
            SELECT source_value, source_value #>> '{}' AS source_id, ordinal
            FROM jsonb_array_elements(stage_data->'source_run_ids')
                 WITH ORDINALITY AS item(source_value, ordinal)
        ) AS source_ids;
        IF source_bad > 0
           OR source_total <> source_distinct
           OR source_original IS DISTINCT FROM source_sorted
        THEN
            RETURN FALSE;
        END IF;
    END LOOP;
    RETURN TRUE;
EXCEPTION
    WHEN invalid_datetime_format OR datetime_field_overflow THEN
        RETURN FALSE;
END;
$$;

CREATE TABLE IF NOT EXISTS daily_evaluation_runs (
    id UUID PRIMARY KEY,
    run_identity TEXT NOT NULL UNIQUE,
    target_session DATE NOT NULL,
    evaluator_name TEXT NOT NULL,
    evaluator_version TEXT NOT NULL,
    universe_snapshot_id TEXT NOT NULL,
    required_stage_names TEXT[] NOT NULL DEFAULT ARRAY['features']::TEXT[],
    derived_stage_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'started',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (target_session, evaluator_name, evaluator_version, universe_snapshot_id)
);

ALTER TABLE daily_evaluation_runs
    ADD COLUMN IF NOT EXISTS required_stage_names TEXT[];
ALTER TABLE daily_evaluation_runs
    ADD COLUMN IF NOT EXISTS derived_stage_metadata JSONB;
ALTER TABLE daily_evaluation_runs
    ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE daily_evaluation_runs
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
ALTER TABLE daily_evaluation_runs
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
CREATE TABLE IF NOT EXISTS ingestion_run_manifests (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES daily_evaluation_runs(id) ON DELETE CASCADE,
    dataset TEXT NOT NULL,
    target_session DATE NOT NULL,
    provider TEXT NOT NULL,
    source_endpoint TEXT NOT NULL,
    entitlement_class TEXT NOT NULL,
    delay_class TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    expected_symbol_count INTEGER NOT NULL CHECK (expected_symbol_count >= 0),
    received_symbol_count INTEGER NOT NULL CHECK (received_symbol_count >= 0),
    expected_row_count BIGINT NOT NULL CHECK (expected_row_count >= 0),
    received_row_count BIGINT NOT NULL CHECK (received_row_count >= 0),
    retry_count INTEGER NOT NULL CHECK (retry_count >= 0),
    status TEXT NOT NULL CHECK (status IN ('started', 'completed', 'data_incomplete', 'failed')),
    raw_payload_sha256 TEXT,
    immutable_object_ref TEXT,
    parser_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    quality_gate TEXT NOT NULL CHECK (quality_gate IN ('not_run', 'passed', 'failed')),
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(provenance) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((raw_payload_sha256 IS NULL) <> (immutable_object_ref IS NULL)),
    CHECK (raw_payload_sha256 IS NULL OR raw_payload_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (
        immutable_object_ref IS NULL
        OR wolfy_is_canonical_ledger_text(immutable_object_ref)
    ),
    CHECK (status <> 'completed' OR completed_at IS NOT NULL),
    UNIQUE (run_id, dataset, provider, source_endpoint)
);

ALTER TABLE ingestion_run_manifests
    ADD COLUMN IF NOT EXISTS immutable_object_ref TEXT;
ALTER TABLE ingestion_run_manifests
    ADD COLUMN IF NOT EXISTS provenance JSONB;
ALTER TABLE ingestion_run_manifests
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
ALTER TABLE ingestion_run_manifests
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_ingestion_run_manifests_run_status
    ON ingestion_run_manifests(run_id, status, quality_gate);

CREATE TABLE IF NOT EXISTS setup_gate_evaluations (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES daily_evaluation_runs(id) ON DELETE CASCADE,
    ticker TEXT NOT NULL CHECK (
        wolfy_is_canonical_ledger_text(ticker) AND ticker = upper(ticker)
    ),
    strategy TEXT NOT NULL CHECK (wolfy_is_canonical_ledger_text(strategy)),
    passed BOOLEAN NOT NULL,
    reason_code_version INTEGER NOT NULL CHECK (reason_code_version IN (1, 2)),
    reason_codes TEXT[] NOT NULL,
    terminal_reason TEXT NOT NULL,
    failed_gates JSONB NOT NULL,
    gate_facts JSONB NOT NULL CHECK (jsonb_typeof(gate_facts) = 'object'),
    source_fingerprint TEXT NOT NULL CHECK (
        wolfy_is_canonical_ledger_text(source_fingerprint)
    ),
    evaluated_at TIMESTAMPTZ NOT NULL,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metrics) = 'object'),
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(provenance) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, ticker, strategy)
);

ALTER TABLE setup_gate_evaluations
    ADD COLUMN IF NOT EXISTS terminal_reason TEXT;
ALTER TABLE setup_gate_evaluations
    ADD COLUMN IF NOT EXISTS failed_gates JSONB;
ALTER TABLE setup_gate_evaluations
    ADD COLUMN IF NOT EXISTS gate_facts JSONB;
ALTER TABLE setup_gate_evaluations
    ADD COLUMN IF NOT EXISTS source_fingerprint TEXT;
ALTER TABLE setup_gate_evaluations
    ADD COLUMN IF NOT EXISTS metrics JSONB;
ALTER TABLE setup_gate_evaluations
    ADD COLUMN IF NOT EXISTS provenance JSONB;
ALTER TABLE setup_gate_evaluations
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
ALTER TABLE setup_gate_evaluations
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

-- Fail closed on populated partial run/manifest schemas before any backfill.
-- Newly introduced nullable audit columns may be NULL and are backfilled below;
-- every value that was already populated must already be canonical.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM daily_evaluation_runs AS run
        WHERE run.run_identity IS NULL
           OR run.run_identity IS DISTINCT FROM wolfy_daily_run_identity(
               run.target_session,
               run.evaluator_name,
               run.evaluator_version,
               run.universe_snapshot_id
           )
           OR NOT wolfy_is_canonical_ledger_text(run.run_identity)
           OR run.evaluator_name IS NULL
           OR NOT wolfy_is_canonical_ledger_text(run.evaluator_name)
           OR run.evaluator_version IS NULL
           OR NOT wolfy_is_canonical_ledger_text(run.evaluator_version)
           OR run.universe_snapshot_id IS NULL
           OR NOT wolfy_is_canonical_ledger_text(run.universe_snapshot_id)
           OR (run.status IS NOT NULL AND run.status NOT IN (
               'started', 'data_incomplete', 'evaluated', 'published', 'failed'
           ))
           OR (
               run.required_stage_names IS NOT NULL
               AND (
                   cardinality(run.required_stage_names) = 0
                   OR EXISTS (
                       SELECT 1 FROM unnest(run.required_stage_names) AS stage(value)
                       WHERE stage.value IS NULL
                          OR NOT wolfy_is_canonical_ledger_text(stage.value)
                   )
                   OR run.required_stage_names IS DISTINCT FROM (
                       SELECT array_agg(stage.value ORDER BY stage.value)
                       FROM unnest(run.required_stage_names) AS stage(value)
                   )
                   OR cardinality(run.required_stage_names) <> (
                       SELECT count(DISTINCT stage.value)
                       FROM unnest(run.required_stage_names) AS stage(value)
                   )
               )
           )
           OR (
               run.derived_stage_metadata IS NOT NULL
               AND NOT wolfy_is_valid_derived_stage_metadata(
                   run.derived_stage_metadata,
                   COALESCE(run.required_stage_names, ARRAY['features']::TEXT[]),
                   run.target_session,
                   run.universe_snapshot_id
               )
           )
           OR (
               run.created_at IS NOT NULL AND run.updated_at IS NOT NULL
               AND run.updated_at < run.created_at
           )
    ) OR EXISTS (
        SELECT 1 FROM daily_evaluation_runs
        GROUP BY run_identity HAVING count(*) > 1
    ) OR EXISTS (
        SELECT 1 FROM daily_evaluation_runs
        GROUP BY target_session, evaluator_name, evaluator_version, universe_snapshot_id
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'cannot migrate legacy daily_evaluation_runs: row violates canonical run contract';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM ingestion_run_manifests AS manifest
        LEFT JOIN daily_evaluation_runs AS run ON run.id = manifest.run_id
        WHERE run.id IS NULL
           OR manifest.target_session IS DISTINCT FROM run.target_session
           OR manifest.dataset IS NULL
           OR NOT wolfy_is_canonical_ledger_text(manifest.dataset)
           OR manifest.provider IS NULL
           OR NOT wolfy_is_canonical_ledger_text(manifest.provider)
           OR manifest.source_endpoint IS NULL
           OR NOT wolfy_is_canonical_ledger_text(manifest.source_endpoint)
           OR manifest.entitlement_class IS NULL
           OR NOT wolfy_is_canonical_ledger_text(manifest.entitlement_class)
           OR manifest.delay_class IS NULL
           OR NOT wolfy_is_canonical_ledger_text(manifest.delay_class)
           OR manifest.parser_version IS NULL
           OR NOT wolfy_is_canonical_ledger_text(manifest.parser_version)
           OR manifest.schema_version IS NULL
           OR NOT wolfy_is_canonical_ledger_text(manifest.schema_version)
           OR manifest.expected_symbol_count IS NULL
           OR manifest.expected_symbol_count < 0
           OR manifest.received_symbol_count IS NULL
           OR manifest.received_symbol_count < 0
           OR manifest.expected_row_count IS NULL
           OR manifest.expected_row_count < 0
           OR manifest.received_row_count IS NULL
           OR manifest.received_row_count < 0
           OR manifest.retry_count IS NULL
           OR manifest.retry_count < 0
           OR manifest.status IS NULL
           OR manifest.status NOT IN ('started', 'completed', 'data_incomplete', 'failed')
           OR manifest.quality_gate IS NULL
           OR manifest.quality_gate NOT IN ('not_run', 'passed', 'failed')
           OR (manifest.status = 'completed' AND manifest.completed_at IS NULL)
           OR manifest.started_at IS NULL
           OR (manifest.completed_at IS NOT NULL AND manifest.completed_at < manifest.started_at)
           OR (
               manifest.provenance IS NOT NULL
               AND jsonb_typeof(manifest.provenance) IS DISTINCT FROM 'object'
           )
           OR NOT (
               (manifest.raw_payload_sha256 IS NOT NULL)
               <> (manifest.immutable_object_ref IS NOT NULL)
           )
           OR (
               manifest.raw_payload_sha256 IS NOT NULL
               AND manifest.raw_payload_sha256 !~ '^[0-9a-f]{64}$'
           )
           OR (
               manifest.immutable_object_ref IS NOT NULL
               AND NOT wolfy_is_canonical_ledger_text(manifest.immutable_object_ref)
           )
           OR (
               manifest.created_at IS NOT NULL AND manifest.updated_at IS NOT NULL
               AND manifest.updated_at < manifest.created_at
           )
    ) OR EXISTS (
        SELECT 1 FROM ingestion_run_manifests
        GROUP BY run_id, dataset, provider, source_endpoint HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'cannot migrate legacy ingestion_run_manifests: row violates canonical manifest contract';
    END IF;
END
$$;

-- Validate all populated legacy rows before any clock-dependent backfill.  NULL
-- terminal fields are accepted only where the canonical value is unambiguous.
DO $$
DECLARE
    canonical_reasons CONSTANT TEXT[] := ARRAY[
        'passed', 'missing_current_price', 'missing_current_features',
        'insufficient_history', 'security_ineligible', 'liquidity_failed',
        'market_regime_failed', 'trend_failed', 'breakout_not_confirmed',
        'pullback_shape_failed', 'relative_strength_failed', 'volume_failed',
        'stop_risk_too_wide', 'overextended', 'breadth_unavailable',
        'breadth_failed', 'sector_confirmation_failed', 'event_landmine',
        'option_chain_missing', 'option_liquidity_failed',
        'portfolio_correlation_block', 'daily_limit_block',
        'feature_stale', 'range_expansion_failed', 'reclaim_not_confirmed',
        'volatility_contraction_failed'
    ]::TEXT[];
BEGIN
    IF EXISTS (
        SELECT 1
        FROM setup_gate_evaluations AS gate
        WHERE gate.reason_code_version NOT IN (1, 2)
           OR (gate.reason_code_version = 1 AND gate.reason_codes && ARRAY[
               'feature_stale', 'range_expansion_failed', 'reclaim_not_confirmed',
               'volatility_contraction_failed'
           ]::TEXT[])
           OR cardinality(gate.reason_codes) = 0
           OR NOT gate.reason_codes <@ canonical_reasons
           OR gate.reason_codes IS DISTINCT FROM (
               SELECT array_agg(reason ORDER BY reason)
               FROM unnest(gate.reason_codes) AS reason
           )
           OR cardinality(gate.reason_codes) <> (
               SELECT count(DISTINCT reason)
               FROM unnest(gate.reason_codes) AS reason
           )
           OR (gate.passed AND gate.reason_codes <> ARRAY['passed']::TEXT[])
           OR (NOT gate.passed AND 'passed' = ANY(gate.reason_codes))
           OR (
               gate.terminal_reason IS NULL
               AND NOT (
                   (gate.passed AND gate.reason_codes = ARRAY['passed']::TEXT[])
                   OR (NOT gate.passed AND cardinality(gate.reason_codes) = 1)
               )
           )
           OR (
               gate.terminal_reason IS NOT NULL
               AND (
                   gate.terminal_reason <> ALL(gate.reason_codes)
                   OR (gate.passed AND gate.terminal_reason <> 'passed')
               )
           )
           OR (
               gate.failed_gates IS NOT NULL
               AND (
                   jsonb_typeof(gate.failed_gates) IS DISTINCT FROM 'array'
                   OR (gate.passed AND gate.failed_gates <> '[]'::jsonb)
                   OR (NOT gate.passed AND gate.failed_gates <> to_jsonb(gate.reason_codes))
               )
           )
           OR jsonb_typeof(gate.gate_facts) IS DISTINCT FROM 'object'
           OR jsonb_typeof(gate.metrics) IS DISTINCT FROM 'object'
           OR jsonb_typeof(gate.provenance) IS DISTINCT FROM 'object'
           OR gate.source_fingerprint IS NULL
           OR NOT wolfy_is_canonical_ledger_text(gate.source_fingerprint)
           OR NOT wolfy_is_canonical_ledger_text(gate.ticker)
           OR gate.ticker <> upper(gate.ticker)
           OR gate.strategy IS NULL
           OR NOT wolfy_is_canonical_ledger_text(gate.strategy)
    ) THEN
        RAISE EXCEPTION 'cannot migrate legacy setup_gate_evaluations: row violates canonical version 1 gate contract or lacks a defensible mapping';
    END IF;
END
$$;

UPDATE daily_evaluation_runs
SET required_stage_names = COALESCE(required_stage_names, ARRAY['features']::TEXT[]),
    derived_stage_metadata = COALESCE(derived_stage_metadata, '{}'::jsonb),
    status = COALESCE(status, 'started'),
    created_at = COALESCE(created_at, now()),
    updated_at = COALESCE(updated_at, now())
WHERE required_stage_names IS NULL OR derived_stage_metadata IS NULL
   OR status IS NULL OR created_at IS NULL OR updated_at IS NULL;
ALTER TABLE daily_evaluation_runs
    ALTER COLUMN run_identity SET NOT NULL,
    ALTER COLUMN target_session SET NOT NULL,
    ALTER COLUMN evaluator_name SET NOT NULL,
    ALTER COLUMN evaluator_version SET NOT NULL,
    ALTER COLUMN universe_snapshot_id SET NOT NULL,
    ALTER COLUMN required_stage_names SET DEFAULT ARRAY['features']::TEXT[],
    ALTER COLUMN required_stage_names SET NOT NULL,
    ALTER COLUMN derived_stage_metadata SET DEFAULT '{}'::jsonb,
    ALTER COLUMN derived_stage_metadata SET NOT NULL,
    ALTER COLUMN status SET DEFAULT 'started',
    ALTER COLUMN status SET NOT NULL,
    ALTER COLUMN created_at SET DEFAULT now(),
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN updated_at SET DEFAULT now(),
    ALTER COLUMN updated_at SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_daily_evaluation_runs_session_status
    ON daily_evaluation_runs(target_session DESC, status);

ALTER TABLE daily_evaluation_runs
    DROP CONSTRAINT IF EXISTS daily_evaluation_runs_status_check,
    DROP CONSTRAINT IF EXISTS daily_evaluation_runs_identity_contract_check,
    DROP CONSTRAINT IF EXISTS daily_evaluation_runs_stage_metadata_check,
    DROP CONSTRAINT IF EXISTS daily_evaluation_runs_chronology_check;
ALTER TABLE daily_evaluation_runs
    ADD CONSTRAINT daily_evaluation_runs_status_check CHECK (
        status IN ('started', 'data_incomplete', 'evaluated', 'published', 'failed')
    ),
    ADD CONSTRAINT daily_evaluation_runs_identity_contract_check CHECK (
        wolfy_is_canonical_ledger_text(run_identity)
        AND wolfy_is_canonical_ledger_text(evaluator_name)
        AND wolfy_is_canonical_ledger_text(evaluator_version)
        AND wolfy_is_canonical_ledger_text(universe_snapshot_id)
    ),
    ADD CONSTRAINT daily_evaluation_runs_stage_metadata_check CHECK (
        cardinality(required_stage_names) > 0
        AND wolfy_is_valid_derived_stage_metadata(
            derived_stage_metadata,
            required_stage_names,
            target_session,
            universe_snapshot_id
        )
    ),
    ADD CONSTRAINT daily_evaluation_runs_chronology_check CHECK (
        updated_at >= created_at
    );

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'daily_evaluation_runs_run_identity_canonical_key'
          AND conrelid = 'daily_evaluation_runs'::regclass
    ) THEN
        ALTER TABLE daily_evaluation_runs
            ADD CONSTRAINT daily_evaluation_runs_run_identity_canonical_key
            UNIQUE (run_identity);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'daily_evaluation_runs_identity_tuple_canonical_key'
          AND conrelid = 'daily_evaluation_runs'::regclass
    ) THEN
        ALTER TABLE daily_evaluation_runs
            ADD CONSTRAINT daily_evaluation_runs_identity_tuple_canonical_key
            UNIQUE (target_session, evaluator_name, evaluator_version, universe_snapshot_id);
    END IF;
END
$$;

UPDATE ingestion_run_manifests
SET provenance = COALESCE(provenance, '{}'::jsonb),
    created_at = COALESCE(created_at, now()),
    updated_at = COALESCE(updated_at, now())
WHERE provenance IS NULL OR created_at IS NULL OR updated_at IS NULL;
ALTER TABLE ingestion_run_manifests
    ALTER COLUMN run_id SET NOT NULL,
    ALTER COLUMN dataset SET NOT NULL,
    ALTER COLUMN target_session SET NOT NULL,
    ALTER COLUMN provider SET NOT NULL,
    ALTER COLUMN source_endpoint SET NOT NULL,
    ALTER COLUMN entitlement_class SET NOT NULL,
    ALTER COLUMN delay_class SET NOT NULL,
    ALTER COLUMN started_at SET NOT NULL,
    ALTER COLUMN expected_symbol_count SET NOT NULL,
    ALTER COLUMN received_symbol_count SET NOT NULL,
    ALTER COLUMN expected_row_count SET NOT NULL,
    ALTER COLUMN received_row_count SET NOT NULL,
    ALTER COLUMN retry_count SET NOT NULL,
    ALTER COLUMN status SET NOT NULL,
    ALTER COLUMN parser_version SET NOT NULL,
    ALTER COLUMN schema_version SET NOT NULL,
    ALTER COLUMN quality_gate SET NOT NULL,
    ALTER COLUMN provenance SET DEFAULT '{}'::jsonb,
    ALTER COLUMN provenance SET NOT NULL,
    ALTER COLUMN created_at SET DEFAULT now(),
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN updated_at SET DEFAULT now(),
    ALTER COLUMN updated_at SET NOT NULL;

ALTER TABLE ingestion_run_manifests
    DROP CONSTRAINT IF EXISTS ingestion_run_manifests_check,
    DROP CONSTRAINT IF EXISTS ingestion_run_manifests_raw_payload_sha256_check,
    DROP CONSTRAINT IF EXISTS ingestion_run_manifests_immutable_object_ref_check,
    DROP CONSTRAINT IF EXISTS ingestion_run_manifests_payload_identity_check,
    DROP CONSTRAINT IF EXISTS ingestion_run_manifests_chronology_check,
    DROP CONSTRAINT IF EXISTS ingestion_run_manifests_contract_check;
ALTER TABLE ingestion_run_manifests
    ADD CONSTRAINT ingestion_run_manifests_payload_identity_check CHECK (
        (raw_payload_sha256 IS NULL) <> (immutable_object_ref IS NULL)
        AND (raw_payload_sha256 IS NULL OR raw_payload_sha256 ~ '^[0-9a-f]{64}$')
        AND (
            immutable_object_ref IS NULL
            OR wolfy_is_canonical_ledger_text(immutable_object_ref)
        )
    ),
    ADD CONSTRAINT ingestion_run_manifests_chronology_check CHECK (
        completed_at IS NULL OR completed_at >= started_at
    ),
    ADD CONSTRAINT ingestion_run_manifests_contract_check CHECK (
        wolfy_is_canonical_ledger_text(dataset)
        AND wolfy_is_canonical_ledger_text(provider)
        AND wolfy_is_canonical_ledger_text(source_endpoint)
        AND wolfy_is_canonical_ledger_text(entitlement_class)
        AND wolfy_is_canonical_ledger_text(delay_class)
        AND wolfy_is_canonical_ledger_text(parser_version)
        AND wolfy_is_canonical_ledger_text(schema_version)
        AND expected_symbol_count >= 0 AND received_symbol_count >= 0
        AND expected_row_count >= 0 AND received_row_count >= 0
        AND retry_count >= 0
        AND status IN ('started', 'completed', 'data_incomplete', 'failed')
        AND quality_gate IN ('not_run', 'passed', 'failed')
        AND (status <> 'completed' OR completed_at IS NOT NULL)
        AND jsonb_typeof(provenance) = 'object'
        AND updated_at >= created_at
    );

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ingestion_run_manifests_identity_canonical_key'
          AND conrelid = 'ingestion_run_manifests'::regclass
    ) THEN
        ALTER TABLE ingestion_run_manifests
            ADD CONSTRAINT ingestion_run_manifests_identity_canonical_key
            UNIQUE (run_id, dataset, provider, source_endpoint);
    END IF;
END
$$;

UPDATE setup_gate_evaluations
SET terminal_reason = CASE
        WHEN terminal_reason IS NOT NULL THEN terminal_reason
        WHEN passed AND reason_codes = ARRAY['passed']::TEXT[] THEN 'passed'
        WHEN NOT passed AND cardinality(reason_codes) = 1 THEN reason_codes[1]
        ELSE NULL
    END,
    failed_gates = COALESCE(
        failed_gates,
        CASE WHEN passed THEN '[]'::jsonb ELSE to_jsonb(reason_codes) END
    ),
    metrics = COALESCE(metrics, '{}'::jsonb),
    provenance = COALESCE(provenance, '{}'::jsonb),
    created_at = COALESCE(created_at, now()),
    updated_at = COALESCE(updated_at, now())
WHERE terminal_reason IS NULL OR failed_gates IS NULL OR metrics IS NULL
   OR provenance IS NULL OR created_at IS NULL OR updated_at IS NULL;

DO $$
DECLARE
    canonical_reasons CONSTANT TEXT[] := ARRAY[
        'passed', 'missing_current_price', 'missing_current_features',
        'insufficient_history', 'security_ineligible', 'liquidity_failed',
        'market_regime_failed', 'trend_failed', 'breakout_not_confirmed',
        'pullback_shape_failed', 'relative_strength_failed', 'volume_failed',
        'stop_risk_too_wide', 'overextended', 'breadth_unavailable',
        'breadth_failed', 'sector_confirmation_failed', 'event_landmine',
        'option_chain_missing', 'option_liquidity_failed',
        'portfolio_correlation_block', 'daily_limit_block',
        'feature_stale', 'range_expansion_failed', 'reclaim_not_confirmed',
        'volatility_contraction_failed'
    ]::TEXT[];
BEGIN
    IF EXISTS (
        SELECT 1 FROM setup_gate_evaluations AS gate
        WHERE gate.reason_code_version NOT IN (1, 2)
           OR (gate.reason_code_version = 1 AND gate.reason_codes && ARRAY[
               'feature_stale', 'range_expansion_failed', 'reclaim_not_confirmed',
               'volatility_contraction_failed'
           ]::TEXT[])
           OR cardinality(gate.reason_codes) = 0
           OR NOT gate.reason_codes <@ canonical_reasons
           OR gate.reason_codes IS DISTINCT FROM (
               SELECT array_agg(reason ORDER BY reason)
               FROM unnest(gate.reason_codes) AS reason
           )
           OR cardinality(gate.reason_codes) <> (
               SELECT count(DISTINCT reason)
               FROM unnest(gate.reason_codes) AS reason
           )
           OR (gate.passed AND gate.reason_codes <> ARRAY['passed']::TEXT[])
           OR (NOT gate.passed AND 'passed' = ANY(gate.reason_codes))
           OR gate.terminal_reason <> ALL(gate.reason_codes)
           OR (gate.passed AND gate.terminal_reason <> 'passed')
           OR jsonb_typeof(gate.failed_gates) IS DISTINCT FROM 'array'
           OR (gate.passed AND gate.failed_gates <> '[]'::jsonb)
           OR (NOT gate.passed AND gate.failed_gates <> to_jsonb(gate.reason_codes))
           OR jsonb_typeof(gate.gate_facts) IS DISTINCT FROM 'object'
           OR jsonb_typeof(gate.metrics) IS DISTINCT FROM 'object'
           OR jsonb_typeof(gate.provenance) IS DISTINCT FROM 'object'
           OR gate.source_fingerprint IS NULL
           OR NOT wolfy_is_canonical_ledger_text(gate.source_fingerprint)
           OR NOT wolfy_is_canonical_ledger_text(gate.ticker)
           OR gate.ticker <> upper(gate.ticker)
           OR gate.strategy IS NULL
           OR NOT wolfy_is_canonical_ledger_text(gate.strategy)
    ) THEN
        RAISE EXCEPTION 'cannot migrate legacy setup_gate_evaluations: canonical backfill validation failed';
    END IF;
END
$$;

ALTER TABLE setup_gate_evaluations
    ALTER COLUMN terminal_reason SET NOT NULL,
    ALTER COLUMN failed_gates SET NOT NULL,
    ALTER COLUMN gate_facts SET NOT NULL,
    ALTER COLUMN source_fingerprint SET NOT NULL,
    ALTER COLUMN metrics SET DEFAULT '{}'::jsonb,
    ALTER COLUMN metrics SET NOT NULL,
    ALTER COLUMN provenance SET DEFAULT '{}'::jsonb,
    ALTER COLUMN provenance SET NOT NULL,
    ALTER COLUMN created_at SET DEFAULT now(),
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN updated_at SET DEFAULT now(),
    ALTER COLUMN updated_at SET NOT NULL;
ALTER TABLE setup_gate_evaluations
    DROP CONSTRAINT IF EXISTS setup_gate_evaluations_reason_codes_check,
    DROP CONSTRAINT IF EXISTS setup_gate_evaluations_text_contract_check;
ALTER TABLE setup_gate_evaluations
    ADD CONSTRAINT setup_gate_evaluations_text_contract_check CHECK (
        wolfy_is_canonical_ledger_text(ticker)
        AND ticker = upper(ticker)
        AND wolfy_is_canonical_ledger_text(strategy)
        AND wolfy_is_canonical_ledger_text(source_fingerprint)
    );

CREATE OR REPLACE FUNCTION wolfy_validate_ingestion_manifest()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    parent_session DATE;
BEGIN
    SELECT target_session INTO parent_session
    FROM daily_evaluation_runs
    WHERE id = NEW.run_id;

    IF parent_session IS NULL OR NEW.target_session IS DISTINCT FROM parent_session THEN
        RAISE EXCEPTION 'ingestion manifest target_session must match parent run';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_ingestion_manifest ON ingestion_run_manifests;
CREATE TRIGGER trg_validate_ingestion_manifest
    BEFORE INSERT OR UPDATE ON ingestion_run_manifests
    FOR EACH ROW EXECUTE FUNCTION wolfy_validate_ingestion_manifest();

CREATE OR REPLACE FUNCTION wolfy_reject_published_ledger_change()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    candidate_run_id UUID;
    parent_status TEXT;
BEGIN
    -- UPDATE must protect both sides: otherwise a row can be reparented away from
    -- a published run or moved into one.  Stable UUID ordering avoids deadlocks.
    FOR candidate_run_id IN
        SELECT DISTINCT run_id
        FROM unnest(
            CASE TG_OP
                WHEN 'INSERT' THEN ARRAY[NEW.run_id]::UUID[]
                WHEN 'DELETE' THEN ARRAY[OLD.run_id]::UUID[]
                ELSE ARRAY[OLD.run_id, NEW.run_id]::UUID[]
            END
        ) AS run_id
        ORDER BY run_id
    LOOP
        SELECT status INTO parent_status
        FROM daily_evaluation_runs
        WHERE id = candidate_run_id
        FOR UPDATE;
        IF parent_status = 'published' THEN
            RAISE EXCEPTION 'published daily evaluation run is immutable';
        END IF;
    END LOOP;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

DROP TRIGGER IF EXISTS trg_immutable_published_manifest ON ingestion_run_manifests;
CREATE TRIGGER trg_immutable_published_manifest
    BEFORE INSERT OR UPDATE OR DELETE ON ingestion_run_manifests
    FOR EACH ROW EXECUTE FUNCTION wolfy_reject_published_ledger_change();

DROP TRIGGER IF EXISTS trg_immutable_published_gate ON setup_gate_evaluations;
CREATE TRIGGER trg_immutable_published_gate
    BEFORE INSERT OR UPDATE OR DELETE ON setup_gate_evaluations
    FOR EACH ROW EXECUTE FUNCTION wolfy_reject_published_ledger_change();

CREATE OR REPLACE FUNCTION wolfy_validate_setup_gate_evaluation()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    canonical_reasons CONSTANT TEXT[] := ARRAY[
        'passed', 'missing_current_price', 'missing_current_features',
        'insufficient_history', 'security_ineligible', 'liquidity_failed',
        'market_regime_failed', 'trend_failed', 'breakout_not_confirmed',
        'pullback_shape_failed', 'relative_strength_failed', 'volume_failed',
        'stop_risk_too_wide', 'overextended', 'breadth_unavailable',
        'breadth_failed', 'sector_confirmation_failed', 'event_landmine',
        'option_chain_missing', 'option_liquidity_failed',
        'portfolio_correlation_block', 'daily_limit_block',
        'feature_stale', 'range_expansion_failed', 'reclaim_not_confirmed',
        'volatility_contraction_failed'
    ]::TEXT[];
    sorted_reasons TEXT[];
BEGIN
    SELECT array_agg(reason ORDER BY reason)
    INTO sorted_reasons
    FROM unnest(NEW.reason_codes) AS reason;

    IF NEW.reason_code_version NOT IN (1, 2)
       OR (NEW.reason_code_version = 1 AND NEW.reason_codes && ARRAY[
           'feature_stale', 'range_expansion_failed', 'reclaim_not_confirmed',
           'volatility_contraction_failed'
       ]::TEXT[])
       OR cardinality(NEW.reason_codes) = 0
       OR NOT NEW.reason_codes <@ canonical_reasons
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

DROP TRIGGER IF EXISTS trg_validate_setup_gate_evaluation ON setup_gate_evaluations;
CREATE TRIGGER trg_validate_setup_gate_evaluation
    BEFORE INSERT OR UPDATE ON setup_gate_evaluations
    FOR EACH ROW EXECUTE FUNCTION wolfy_validate_setup_gate_evaluation();

CREATE INDEX IF NOT EXISTS idx_setup_gate_evaluations_run_passed
    ON setup_gate_evaluations(run_id, passed, ticker, strategy);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'daily_evaluation_runs_stage_metadata_check'
          AND conrelid = 'daily_evaluation_runs'::regclass
    ) THEN
        ALTER TABLE daily_evaluation_runs
            ADD CONSTRAINT daily_evaluation_runs_stage_metadata_check CHECK (
                cardinality(required_stage_names) > 0
                AND wolfy_is_valid_derived_stage_metadata(
                    derived_stage_metadata,
                    required_stage_names,
                    target_session,
                    universe_snapshot_id
                )
            );
    END IF;
END
$$;

CREATE OR REPLACE FUNCTION wolfy_validate_daily_run_transition()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    manifest_ready INTEGER;
    stage_name TEXT;
    stage_data JSONB;
    source_total INTEGER;
    source_distinct INTEGER;
    source_bad INTEGER;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status = 'published' THEN
            RAISE EXCEPTION 'published daily evaluation run is immutable and cannot be deleted';
        END IF;
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.status = 'published' THEN
        IF NEW IS DISTINCT FROM OLD THEN
            RAISE EXCEPTION 'published daily evaluation run identity, readiness, and audit fields are immutable';
        END IF;
        -- Preserve a truly idempotent no-op without changing updated_at.
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' AND (
        NEW.run_identity IS DISTINCT FROM OLD.run_identity
        OR NEW.target_session IS DISTINCT FROM OLD.target_session
        OR NEW.evaluator_name IS DISTINCT FROM OLD.evaluator_name
        OR NEW.evaluator_version IS DISTINCT FROM OLD.evaluator_version
        OR NEW.universe_snapshot_id IS DISTINCT FROM OLD.universe_snapshot_id
    ) THEN
        RAISE EXCEPTION 'daily evaluation run identity tuple is immutable after insert';
    END IF;
    IF TG_OP = 'UPDATE'
       AND NEW.required_stage_names IS DISTINCT FROM OLD.required_stage_names
    THEN
        RAISE EXCEPTION 'daily evaluation run required stages are immutable after insert';
    END IF;
    IF NEW.run_identity IS DISTINCT FROM wolfy_daily_run_identity(
        NEW.target_session,
        NEW.evaluator_name,
        NEW.evaluator_version,
        NEW.universe_snapshot_id
    ) THEN
        RAISE EXCEPTION 'daily evaluation run_identity does not match deterministic identity tuple';
    END IF;
    IF cardinality(NEW.required_stage_names) = 0
       OR EXISTS (
           SELECT 1 FROM unnest(NEW.required_stage_names) AS stage(value)
           WHERE stage.value IS NULL
              OR NOT wolfy_is_canonical_ledger_text(stage.value)
       )
       OR NEW.required_stage_names IS DISTINCT FROM (
           SELECT array_agg(stage.value ORDER BY stage.value)
           FROM unnest(NEW.required_stage_names) AS stage(value)
       )
       OR cardinality(NEW.required_stage_names) <> (
           SELECT count(DISTINCT stage.value)
           FROM unnest(NEW.required_stage_names) AS stage(value)
       )
       OR NOT wolfy_is_valid_derived_stage_metadata(
           NEW.derived_stage_metadata,
           NEW.required_stage_names,
           NEW.target_session,
           NEW.universe_snapshot_id
       )
    THEN
        RAISE EXCEPTION 'noncanonical daily evaluation run stages or derived stage metadata';
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.status <> OLD.status THEN
        IF NOT (
            (OLD.status = 'started' AND NEW.status IN ('data_incomplete', 'evaluated', 'failed'))
            OR (OLD.status = 'data_incomplete' AND NEW.status IN ('evaluated', 'failed'))
            OR (OLD.status = 'evaluated' AND NEW.status IN ('published', 'failed'))
        ) THEN
            RAISE EXCEPTION 'invalid daily evaluation run transition: % -> %', OLD.status, NEW.status;
        END IF;
    END IF;
    IF NEW.status = 'published' THEN
        SELECT count(*) INTO manifest_ready
        FROM ingestion_run_manifests
        WHERE run_id = NEW.id
          AND target_session = NEW.target_session
          AND status = 'completed'
          AND completed_at IS NOT NULL
          AND quality_gate = 'passed'
          AND expected_symbol_count = received_symbol_count
          AND expected_row_count = received_row_count;
        IF manifest_ready = 0 THEN
            RAISE EXCEPTION 'published run requires complete passed ingestion manifest for target session';
        END IF;
        IF cardinality(NEW.required_stage_names) = 0
           OR EXISTS (
               SELECT 1 FROM unnest(NEW.required_stage_names) AS required_stage(value)
               WHERE NOT wolfy_is_canonical_ledger_text(required_stage.value)
           )
           OR cardinality(NEW.required_stage_names) <> (
               SELECT count(DISTINCT required_stage.value)
               FROM unnest(NEW.required_stage_names) AS required_stage(value)
           )
        THEN
            RAISE EXCEPTION 'published run has invalid required derived stages';
        END IF;
        FOREACH stage_name IN ARRAY NEW.required_stage_names LOOP
            stage_data := NEW.derived_stage_metadata -> stage_name;
            IF stage_data IS NULL
               OR jsonb_typeof(stage_data) <> 'object'
               OR (SELECT count(*) FROM jsonb_object_keys(stage_data)) <> 8
               OR NOT stage_data ?& ARRAY[
                   'input_session', 'computed_at', 'available_at',
                   'transformation_version', 'source_run_ids', 'input_hash',
                   'universe_snapshot_id', 'provenance'
               ]
               OR stage_data->>'input_session' <> NEW.target_session::text
               OR stage_data->>'computed_at' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]+)?(Z|[+]00:00)$'
               OR stage_data->>'available_at' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]+)?(Z|[+]00:00)$'
               OR (stage_data->>'available_at')::timestamptz < (stage_data->>'computed_at')::timestamptz
               OR NOT wolfy_is_canonical_ledger_text(stage_data->>'transformation_version')
               OR jsonb_typeof(stage_data->'source_run_ids') <> 'array'
               OR jsonb_array_length(stage_data->'source_run_ids') = 0
               OR stage_data->>'input_hash' !~ '^[0-9a-f]{64}$'
               OR NOT wolfy_is_canonical_ledger_text(stage_data->>'universe_snapshot_id')
               OR stage_data->>'universe_snapshot_id' <> NEW.universe_snapshot_id
               OR jsonb_typeof(stage_data->'provenance') <> 'object'
            THEN
                RAISE EXCEPTION 'published run missing complete derived stage metadata: %', stage_name;
            END IF;
            SELECT count(*), count(DISTINCT source_id), count(*) FILTER (
                WHERE jsonb_typeof(source_value) <> 'string'
                   OR NOT wolfy_is_canonical_ledger_text(source_id)
            )
            INTO source_total, source_distinct, source_bad
            FROM (
                SELECT source_value, source_value #>> '{}' AS source_id
                FROM jsonb_array_elements(stage_data->'source_run_ids') AS source_value
            ) AS source_ids;
            IF source_bad > 0 OR source_total <> source_distinct THEN
                RAISE EXCEPTION 'published run has invalid derived stage source IDs: %', stage_name;
            END IF;
        END LOOP;
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_daily_evaluation_run_transition ON daily_evaluation_runs;
CREATE TRIGGER trg_daily_evaluation_run_transition
    BEFORE INSERT OR UPDATE OR DELETE ON daily_evaluation_runs
    FOR EACH ROW EXECUTE FUNCTION wolfy_validate_daily_run_transition();

COMMIT;
