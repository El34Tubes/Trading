-- Wolfy/Jonah/Sentinel Postgres scale-up schema
-- PostgreSQL 16 + pgvector foundation. SQLite remains the current source of truth until migration is complete.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS agent_tasks (
    id BIGSERIAL PRIMARY KEY,
    agent_name TEXT NOT NULL,
    task_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 50,
    claim_token TEXT,
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    source_fingerprint TEXT,
    topic_tags TEXT[] DEFAULT '{}',
    ticker_symbols TEXT[] DEFAULT '{}',
    depends_on BIGINT REFERENCES agent_tasks(id),
    supersedes BIGINT REFERENCES agent_tasks(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_tasks_status_agent ON agent_tasks(status, agent_name, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_source_fingerprint ON agent_tasks(source_fingerprint);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_tags_gin ON agent_tasks USING gin(topic_tags);
CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_tasks_dedupe_fingerprint
    ON agent_tasks(agent_name, task_type, source_fingerprint)
    WHERE source_fingerprint IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agent_tasks_claimable
    ON agent_tasks(agent_name, task_type, priority, created_at)
    WHERE status = 'queued';

ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS error_message TEXT;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS payload JSONB;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS agent TEXT;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS assigned_agent TEXT;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS type TEXT;
UPDATE agent_tasks
SET agent=agent_name
WHERE agent IS NULL;
UPDATE agent_tasks
SET assigned_agent=agent_name
WHERE assigned_agent IS NULL;
UPDATE agent_tasks
SET type=task_type
WHERE type IS NULL;
UPDATE agent_tasks
SET summary=description
WHERE summary IS NULL AND description IS NOT NULL;
UPDATE agent_tasks
SET error_message=COALESCE(error_message, summary, description)
WHERE status='blocked' AND error_message IS NULL;
UPDATE agent_tasks
SET payload = jsonb_strip_nulls(jsonb_build_object(
    'id', id,
    'agent_name', agent_name,
    'agent', agent,
    'assigned_agent', assigned_agent,
    'task_type', task_type,
    'type', type,
    'title', title,
    'description', description,
    'status', status,
    'priority', priority,
    'source_fingerprint', source_fingerprint,
    'topic_tags', topic_tags,
    'ticker_symbols', ticker_symbols,
    'depends_on', depends_on,
    'supersedes', supersedes,
    'created_at', created_at,
    'updated_at', updated_at,
    'summary', summary,
    'error_message', error_message
))
WHERE payload IS NULL;

CREATE TABLE IF NOT EXISTS agent_runs (
    id BIGSERIAL PRIMARY KEY,
    agent_name TEXT NOT NULL,
    role TEXT NOT NULL,
    job_id TEXT,
    task_id BIGINT REFERENCES agent_tasks(id),
    task_type TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'started',
    input_tokens BIGINT,
    output_tokens BIGINT,
    total_tokens BIGINT,
    estimated_cost NUMERIC(12,6),
    records_created INTEGER DEFAULT 0,
    summary TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_agent_started ON agent_runs(agent_name, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent_runs(status);

ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS task_type TEXT;
UPDATE agent_runs ar
SET task_type=at.task_type
FROM agent_tasks at
WHERE ar.task_id = at.id
  AND ar.task_type IS NULL;

CREATE TABLE IF NOT EXISTS agent_artifacts (
    id BIGSERIAL PRIMARY KEY,
    agent_name TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    source_url TEXT,
    -- Compatibility mirror for ad-hoc/read-only probes that expect a
    -- resolved/final URL column. Canonical writes use source_url.
    source_final_url TEXT,
    source_fingerprint TEXT,
    topic_tags TEXT[] DEFAULT '{}',
    ticker_symbols TEXT[] DEFAULT '{}',
    confidence NUMERIC(4,3) DEFAULT 0.500,
    freshness TEXT NOT NULL DEFAULT 'durable',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (artifact_type, source_fingerprint, title)
);

CREATE INDEX IF NOT EXISTS idx_agent_artifacts_agent_type ON agent_artifacts(agent_name, artifact_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_artifacts_body_trgm ON agent_artifacts USING gin(body gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_agent_artifacts_tags_gin ON agent_artifacts USING gin(topic_tags);

ALTER TABLE agent_artifacts ADD COLUMN IF NOT EXISTS source_final_url TEXT;
UPDATE agent_artifacts
SET source_final_url = source_url
WHERE source_final_url IS NULL AND source_url IS NOT NULL;

CREATE OR REPLACE FUNCTION wolfy_sync_agent_artifacts_aliases()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.source_final_url IS NULL THEN
    NEW.source_final_url := NEW.source_url;
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_agent_artifacts_aliases_biu ON agent_artifacts;
CREATE TRIGGER trg_agent_artifacts_aliases_biu
  BEFORE INSERT OR UPDATE OF source_url, source_final_url ON agent_artifacts
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_agent_artifacts_aliases();

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id BIGSERIAL PRIMARY KEY,
    artifact_id BIGINT REFERENCES agent_artifacts(id) ON DELETE CASCADE,
    source_table TEXT,
    source_id TEXT,
    chunk_index INTEGER NOT NULL DEFAULT 0,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    -- Compatibility mirror for ad-hoc/read-only probes. Canonical titles live
    -- on agent_artifacts.title or metadata->>'title' / metadata->>'source_title'.
    title TEXT,
    embedding vector(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(source_table, source_id, chunk_index)
);

ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS title TEXT;
UPDATE knowledge_chunks kc
SET title = COALESCE(kc.title, kc.metadata->>'title', kc.metadata->>'source_title', aa.title, kc.source_table || ':' || kc.source_id)
FROM agent_artifacts aa
WHERE kc.artifact_id = aa.id
  AND kc.title IS NULL;
UPDATE knowledge_chunks
SET title = COALESCE(title, metadata->>'title', metadata->>'source_title', source_table || ':' || source_id)
WHERE title IS NULL;

CREATE OR REPLACE FUNCTION wolfy_sync_knowledge_chunks_aliases()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.title IS NULL THEN
    SELECT COALESCE(NEW.metadata->>'title', NEW.metadata->>'source_title', aa.title, NEW.source_table || ':' || NEW.source_id)
    INTO NEW.title
    FROM agent_artifacts aa
    WHERE aa.id = NEW.artifact_id;
    IF NEW.title IS NULL THEN
      NEW.title := COALESCE(NEW.metadata->>'title', NEW.metadata->>'source_title', NEW.source_table || ':' || NEW.source_id);
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_knowledge_chunks_aliases_biu ON knowledge_chunks;
CREATE TRIGGER trg_knowledge_chunks_aliases_biu
  BEFORE INSERT OR UPDATE OF artifact_id, source_table, source_id, metadata, title ON knowledge_chunks
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_knowledge_chunks_aliases();

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_content_trgm ON knowledge_chunks USING gin(content gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding_hnsw ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS agent_usage_snapshots (
  id BIGSERIAL PRIMARY KEY,
  captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  window_days INTEGER NOT NULL DEFAULT 1,
  sessions INTEGER,
  messages INTEGER,
  tool_calls INTEGER,
  input_tokens BIGINT,
  output_tokens BIGINT,
  total_tokens BIGINT,
  cron_sessions INTEGER,
  cron_messages INTEGER,
  cron_tokens BIGINT,
  cli_sessions INTEGER,
  cli_messages INTEGER,
  cli_tokens BIGINT,
  discord_sessions INTEGER,
  discord_messages INTEGER,
  discord_tokens BIGINT,
  raw_excerpt TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_usage_snapshots_captured ON agent_usage_snapshots(captured_at DESC);

CREATE TABLE IF NOT EXISTS recommendation_reviews (
  id BIGSERIAL PRIMARY KEY,
    recommendation_id BIGINT NOT NULL,
    reviewer_agent TEXT NOT NULL DEFAULT 'Sentinel',
    decision TEXT NOT NULL,
    feasibility_score NUMERIC(4,3),
    risk_score NUMERIC(4,3),
    constraint_check JSONB NOT NULL DEFAULT '{}',
    review_notes TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_recommendation_reviews_rec ON recommendation_reviews(recommendation_id, created_at DESC);

CREATE TABLE IF NOT EXISTS alpha_search_reports (
  id BIGSERIAL PRIMARY KEY,
  sqlite_id BIGINT UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  source_job_id TEXT NOT NULL DEFAULT 'wolfy-alpha-search-report',
  agent_run_id TEXT,
  title TEXT NOT NULL,
  market_context TEXT,
  sections JSONB NOT NULL DEFAULT '{}',
  summary TEXT NOT NULL,
  delivered_to TEXT,
  raw_payload JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_pg_alpha_reports_created ON alpha_search_reports(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pg_alpha_reports_job ON alpha_search_reports(source_job_id, created_at DESC);

CREATE TABLE IF NOT EXISTS alpha_leads (
  id BIGSERIAL PRIMARY KEY,
  sqlite_id BIGINT UNIQUE,
  report_id BIGINT REFERENCES alpha_search_reports(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ticker TEXT NOT NULL,
  lead_type TEXT NOT NULL,
  title TEXT NOT NULL,
  thesis TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new',
  evidence_quality_score NUMERIC(5,3) NOT NULL DEFAULT 0,
  evidence_quality NUMERIC(5,3),
  evidence_count INTEGER NOT NULL DEFAULT 0,
  highest_source_quality NUMERIC(5,3) NOT NULL DEFAULT 0,
  suspicious_action TEXT NOT NULL DEFAULT 'clear',
  suspicious_flags JSONB NOT NULL DEFAULT '[]',
  catalyst_window TEXT,
  social_context TEXT,
  filing_context TEXT,
  insider_context TEXT,
  complete_ticket BOOLEAN NOT NULL DEFAULT false,
  recommendation_id TEXT,
  next_research_question TEXT,
  company_name TEXT,
  scanner_type TEXT,
  market_context JSONB,
  score DOUBLE PRECISION,
  raw_payload JSONB NOT NULL DEFAULT '{}',
  source_fingerprint TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_pg_alpha_leads_ticker_status ON alpha_leads(ticker, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_pg_alpha_leads_quality ON alpha_leads(evidence_quality_score DESC, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_pg_alpha_leads_suspicious ON alpha_leads(suspicious_action, updated_at DESC);

CREATE TABLE IF NOT EXISTS alpha_lead_evidence (
  id BIGSERIAL PRIMARY KEY,
  sqlite_id BIGINT UNIQUE,
  lead_id BIGINT NOT NULL REFERENCES alpha_leads(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  evidence_type TEXT NOT NULL,
  source_title TEXT,
  source_url TEXT,
  source_published_at TEXT,
  quote_or_fact TEXT NOT NULL,
  quality_score NUMERIC(5,3) NOT NULL DEFAULT 0.5,
  relevance_score NUMERIC(5,3) NOT NULL DEFAULT 0.5,
  notes TEXT,
  source_fingerprint TEXT NOT NULL,
  UNIQUE(lead_id, source_fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_pg_alpha_evidence_lead ON alpha_lead_evidence(lead_id, quality_score DESC);

CREATE TABLE IF NOT EXISTS alpha_handoffs (
  id BIGSERIAL PRIMARY KEY,
  sqlite_id BIGINT UNIQUE,
  lead_id BIGINT REFERENCES alpha_leads(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  target_agent TEXT NOT NULL,
  task_type TEXT NOT NULL,
  title TEXT NOT NULL,
  question TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 50,
  status TEXT NOT NULL DEFAULT 'queued',
  postgres_task_id BIGINT REFERENCES agent_tasks(id),
  source_fingerprint TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_pg_alpha_handoffs_agent_status ON alpha_handoffs(target_agent, status, priority, created_at);

-- Non-destructive compatibility aliases for ad-hoc diagnostics and older helper probes.
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS result_summary TEXT;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS task_type TEXT;
UPDATE agent_runs SET completed_at=ended_at WHERE completed_at IS NULL AND ended_at IS NOT NULL;
UPDATE agent_runs SET result_summary=summary WHERE result_summary IS NULL AND summary IS NOT NULL;
UPDATE agent_runs ar
SET task_type=at.task_type
FROM agent_tasks at
WHERE ar.task_id = at.id
  AND ar.task_type IS NULL;

ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS source_table TEXT;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS source_id TEXT;
UPDATE agent_tasks
SET source_table=COALESCE(source_table, payload->>'source_table', 'agent_tasks'),
    source_id=COALESCE(source_id, payload->>'source_id', source_fingerprint, id::text)
WHERE source_table IS NULL OR source_id IS NULL;

ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS scanner_run_id BIGINT;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS company_name TEXT;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS scanner_type TEXT;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS signal TEXT;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS rs_spy_20 DOUBLE PRECISION;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS rs_qqq_20 DOUBLE PRECISION;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS breakout_20d_pct DOUBLE PRECISION;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS volume_surge_1d_20 DOUBLE PRECISION;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS volume_surge_5d_20 DOUBLE PRECISION;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS volume_surge_1d_50 DOUBLE PRECISION;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS volume_surge_5d_50 DOUBLE PRECISION;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS atr_pct DOUBLE PRECISION;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS squeeze_ratio DOUBLE PRECISION;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS squeeze_flag INTEGER;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS liquidity_spread_proxy DOUBLE PRECISION;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS trend_regime TEXT;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS rank_reasons TEXT;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS gap_reversal_flag TEXT;
UPDATE scanner_results
SET scanner_run_id=COALESCE(scanner_run_id, run_id),
    status=COALESCE(status, CASE WHEN liquidity_pass IS FALSE THEN 'filtered' ELSE 'observed' END),
    company_name=COALESCE(company_name, notes->>'company_name', notes->>'company'),
    scanner_type=COALESCE(scanner_type, notes->>'scanner_type', notes->>'signal', notes->>'lead_type'),
    signal=COALESCE(signal, notes->>'signal', notes->>'scanner_type', scanner_type),
    rs_spy_20=COALESCE(rs_spy_20, CASE WHEN (notes->>'rs_spy_20') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (notes->>'rs_spy_20')::double precision END),
    rs_qqq_20=COALESCE(rs_qqq_20, CASE WHEN (notes->>'rs_qqq_20') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (notes->>'rs_qqq_20')::double precision END),
    breakout_20d_pct=COALESCE(breakout_20d_pct, CASE WHEN (notes->>'breakout_20d_pct') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (notes->>'breakout_20d_pct')::double precision END),
    volume_surge_1d_20=COALESCE(volume_surge_1d_20, CASE WHEN (notes->>'volume_surge_1d_20') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (notes->>'volume_surge_1d_20')::double precision END),
    volume_surge_5d_20=COALESCE(volume_surge_5d_20, CASE WHEN (notes->>'volume_surge_5d_20') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (notes->>'volume_surge_5d_20')::double precision END),
    volume_surge_1d_50=COALESCE(volume_surge_1d_50, CASE WHEN (notes->>'volume_surge_1d_50') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (notes->>'volume_surge_1d_50')::double precision END),
    volume_surge_5d_50=COALESCE(volume_surge_5d_50, CASE WHEN (notes->>'volume_surge_5d_50') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (notes->>'volume_surge_5d_50')::double precision END),
    atr_pct=COALESCE(atr_pct, CASE WHEN (notes->>'atr_pct') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (notes->>'atr_pct')::double precision END),
    squeeze_ratio=COALESCE(squeeze_ratio, CASE WHEN (notes->>'squeeze_ratio') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (notes->>'squeeze_ratio')::double precision END),
    squeeze_flag=COALESCE(squeeze_flag, CASE WHEN (notes->>'squeeze_flag') ~ '^-?[0-9]+$' THEN (notes->>'squeeze_flag')::integer END),
    liquidity_spread_proxy=COALESCE(liquidity_spread_proxy, CASE WHEN (notes->>'liquidity_spread_proxy') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (notes->>'liquidity_spread_proxy')::double precision END),
    trend_regime=COALESCE(trend_regime, notes->>'trend_regime'),
    rank_reasons=COALESCE(rank_reasons, notes->>'rank_reasons'),
    gap_reversal_flag=COALESCE(gap_reversal_flag, notes->>'gap_reversal_flag')
WHERE scanner_run_id IS NULL OR status IS NULL OR company_name IS NULL OR scanner_type IS NULL OR signal IS NULL
   OR rs_spy_20 IS NULL OR rs_qqq_20 IS NULL OR breakout_20d_pct IS NULL OR volume_surge_1d_20 IS NULL
   OR volume_surge_5d_20 IS NULL OR volume_surge_1d_50 IS NULL OR volume_surge_5d_50 IS NULL
   OR atr_pct IS NULL OR squeeze_ratio IS NULL OR squeeze_flag IS NULL OR liquidity_spread_proxy IS NULL
   OR trend_regime IS NULL OR rank_reasons IS NULL OR gap_reversal_flag IS NULL;

ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS company_name TEXT;
ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS scanner_type TEXT;
ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS scanner_run_id BIGINT;
ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS market_context JSONB;
ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS score DOUBLE PRECISION;
ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS evidence_quality NUMERIC(5,3);
ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS rationale TEXT;
ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS summary TEXT;
UPDATE alpha_leads
SET company_name=COALESCE(company_name, raw_payload->>'company_name', raw_payload->>'company'),
    scanner_type=COALESCE(scanner_type, raw_payload->>'scanner_type', raw_payload->>'signal', raw_payload->>'lead_type', lead_type),
    scanner_run_id=COALESCE(scanner_run_id,
      CASE WHEN (raw_payload->>'scanner_run_id') ~ '^[0-9]+$' THEN (raw_payload->>'scanner_run_id')::bigint END,
      CASE WHEN (raw_payload->>'scanner_run') ~ '^[0-9]+$' THEN (raw_payload->>'scanner_run')::bigint END,
      CASE WHEN (raw_payload->>'run_id') ~ '^[0-9]+$' THEN (raw_payload->>'run_id')::bigint END),
    market_context=COALESCE(market_context, raw_payload->'market_context'),
    rationale=COALESCE(rationale, thesis, raw_payload->>'rationale', raw_payload->>'summary'),
    summary=COALESCE(summary, raw_payload->>'summary', thesis, title),
    score=COALESCE(score,
      CASE WHEN (raw_payload->>'score') ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (raw_payload->>'score')::double precision END,
      CASE WHEN (raw_payload->>'scanner_score') ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (raw_payload->>'scanner_score')::double precision END,
      evidence_quality_score::double precision),
    evidence_quality=COALESCE(evidence_quality, evidence_quality_score)
WHERE company_name IS NULL OR scanner_type IS NULL OR scanner_run_id IS NULL OR market_context IS NULL OR score IS NULL OR evidence_quality IS NULL OR rationale IS NULL OR summary IS NULL;

ALTER TABLE recommendation_reviews
  ALTER COLUMN recommendation_id TYPE BIGINT USING recommendation_id::bigint;

DROP VIEW IF EXISTS alpha_search_leads;
CREATE VIEW alpha_search_leads AS
SELECT
  id, sqlite_id, report_id, created_at, updated_at, ticker, lead_type, title,
  thesis, rationale, summary, status, evidence_quality_score AS score,
  evidence_quality_score, evidence_quality, evidence_count, highest_source_quality,
  suspicious_action, suspicious_flags, catalyst_window, social_context,
  filing_context, insider_context, complete_ticket, recommendation_id,
  next_research_question, company_name, scanner_type, scanner_run_id, market_context,
  raw_payload, source_fingerprint
FROM alpha_leads;

-- Read-only compatibility view for ad-hoc probes that still query the older
-- SQLite-era strategy_rules name. Canonical EOD strategy state lives in
-- strategies; archived learning rules live in knowledge_chunks.
DROP VIEW IF EXISTS strategy_rules;
CREATE VIEW strategy_rules AS
SELECT
  id::bigint AS id,
  name,
  name AS title,
  NULL::text AS ticker,
  name AS rule_name,
 status,
 status AS scope,
 status AS implementation_status,
  setup_type AS rule_type,
  ARRAY[]::text[] AS ticker_symbols,
  ARRAY[setup_type, status]::text[] AS topic_tags,
  notes AS description,
  notes AS summary,
  notes AS body,
  COALESCE(params, '{}'::jsonb) AS metadata,
  COALESCE(params->>'source','postgres.strategies') AS source_basis,
  (status IN ('approved','candidate')) AS enabled,
  (status IN ('approved','active','candidate')) AS is_active,
  NULL::timestamptz AS created_at,
  NULL::timestamptz AS updated_at,
  'equity_etf_process'::text AS asset_class,
  setup_type AS category,
  id::text AS source_id,
  notes AS rule_text
FROM strategies
UNION ALL
SELECT
  ('1000000000'::bigint + source_id::bigint) AS id,
  btrim(regexp_replace(split_part(content, E'\n', 1), '^Rule:\s*', '')) AS name,
  btrim(regexp_replace(split_part(content, E'\n', 1), '^Rule:\s*', '')) AS title,
  NULL::text AS ticker,
  btrim(regexp_replace(split_part(content, E'\n', 1), '^Rule:\s*', '')) AS rule_name,
  'active'::text AS status,
  'active'::text AS scope,
  'active'::text AS implementation_status,
  NULLIF(btrim(regexp_replace(split_part(content, E'\n', 2), '^Type:\s*', '')), '') AS rule_type,
  ARRAY[]::text[] AS ticker_symbols,
  ARRAY_REMOVE(ARRAY['sqlite.strategy_rules', NULLIF(btrim(regexp_replace(split_part(content, E'\n', 2), '^Type:\s*', '')), '')], NULL)::text[] AS topic_tags,
  btrim(regexp_replace(regexp_replace(content, E'^Rule:[^\n]*\nType:[^\n]*\nDescription:\s*', ''), E'\n+', ' ', 'g')) AS description,
  btrim(regexp_replace(regexp_replace(content, E'^Rule:[^\n]*\nType:[^\n]*\nDescription:\s*', ''), E'\n+', ' ', 'g')) AS summary,
  btrim(regexp_replace(regexp_replace(content, E'^Rule:[^\n]*\nType:[^\n]*\nDescription:\s*', ''), E'\n+', ' ', 'g')) AS body,
  metadata AS metadata,
  'sqlite.strategy_rules'::text AS source_basis,
  true AS enabled,
  true AS is_active,
  created_at AS created_at,
  created_at AS updated_at,
  'equity_etf_process'::text AS asset_class,
  NULLIF(btrim(regexp_replace(split_part(content, E'\n', 2), '^Type:\s*', '')), '') AS category,
  source_id AS source_id,
  btrim(regexp_replace(regexp_replace(content, E'^Rule:[^\n]*\nType:[^\n]*\nDescription:\s*', ''), E'\n+', ' ', 'g')) AS rule_text
FROM knowledge_chunks
WHERE source_table='sqlite.strategy_rules' AND source_id ~ '^[0-9]+$';

CREATE OR REPLACE FUNCTION wolfy_sync_agent_runs_aliases()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.completed_at IS NULL THEN
    NEW.completed_at := NEW.ended_at;
  END IF;
  IF NEW.ended_at IS NULL THEN
    NEW.ended_at := NEW.completed_at;
  END IF;
  IF NEW.result_summary IS NULL THEN
    NEW.result_summary := NEW.summary;
  END IF;
  IF NEW.summary IS NULL THEN
    NEW.summary := NEW.result_summary;
  END IF;
  IF NEW.task_type IS NULL AND NEW.task_id IS NOT NULL THEN
    SELECT at.task_type INTO NEW.task_type
    FROM agent_tasks at
    WHERE at.id = NEW.task_id;
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_agent_runs_aliases_biu ON agent_runs;
CREATE TRIGGER trg_agent_runs_aliases_biu
  BEFORE INSERT OR UPDATE OF task_id, task_type, ended_at, completed_at, summary, result_summary ON agent_runs
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_agent_runs_aliases();

CREATE OR REPLACE FUNCTION wolfy_sync_agent_tasks_aliases()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.type IS NULL THEN
  NEW.type := NEW.task_type;
  END IF;
  IF NEW.summary IS NULL THEN
    NEW.summary := NEW.description;
  END IF;
  IF NEW.status = 'blocked' AND NEW.error_message IS NULL THEN
    NEW.error_message := COALESCE(NEW.summary, NEW.description);
  END IF;
  IF NEW.payload IS NULL THEN
  NEW.payload := jsonb_strip_nulls(jsonb_build_object(
  'id', NEW.id,
  'agent_name', NEW.agent_name,
  'task_type', NEW.task_type,
  'type', NEW.type,
  'title', NEW.title,
  'description', NEW.description,
  'status', NEW.status,
  'priority', NEW.priority,
  'source_fingerprint', NEW.source_fingerprint,
  'topic_tags', NEW.topic_tags,
  'ticker_symbols', NEW.ticker_symbols,
  'depends_on', NEW.depends_on,
  'supersedes', NEW.supersedes,
  'created_at', NEW.created_at,
  'updated_at', NEW.updated_at,
  'summary', NEW.summary,
  'error_message', NEW.error_message,
  'source_table', NEW.source_table,
  'source_id', NEW.source_id
  ));
  END IF;
  IF NEW.source_table IS NULL THEN
  NEW.source_table := COALESCE(NEW.payload->>'source_table', 'agent_tasks');
  END IF;
  IF NEW.source_id IS NULL THEN
  NEW.source_id := COALESCE(NEW.payload->>'source_id', NEW.source_fingerprint, NEW.id::text);
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_agent_tasks_aliases_biu ON agent_tasks;
CREATE TRIGGER trg_agent_tasks_aliases_biu
  BEFORE INSERT OR UPDATE OF task_type, type, description, summary, error_message, status, payload, source_table, source_id ON agent_tasks
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_agent_tasks_aliases();

CREATE OR REPLACE FUNCTION wolfy_sync_alpha_leads_aliases()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.company_name IS NULL THEN
    NEW.company_name := COALESCE(NEW.raw_payload->>'company_name', NEW.raw_payload->>'company');
  END IF;
  IF NEW.scanner_type IS NULL THEN
    NEW.scanner_type := COALESCE(NEW.raw_payload->>'scanner_type', NEW.raw_payload->>'signal', NEW.raw_payload->>'lead_type', NEW.lead_type);
  END IF;
  IF NEW.scanner_run_id IS NULL THEN
    NEW.scanner_run_id := COALESCE(
      CASE WHEN (NEW.raw_payload->>'scanner_run_id') ~ '^[0-9]+$' THEN (NEW.raw_payload->>'scanner_run_id')::bigint END,
      CASE WHEN (NEW.raw_payload->>'scanner_run') ~ '^[0-9]+$' THEN (NEW.raw_payload->>'scanner_run')::bigint END,
      CASE WHEN (NEW.raw_payload->>'run_id') ~ '^[0-9]+$' THEN (NEW.raw_payload->>'run_id')::bigint END
    );
  END IF;
  IF NEW.market_context IS NULL THEN
    NEW.market_context := NEW.raw_payload->'market_context';
  END IF;
  IF NEW.score IS NULL THEN
    NEW.score := COALESCE(
      CASE WHEN (NEW.raw_payload->>'score') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (NEW.raw_payload->>'score')::double precision END,
      CASE WHEN (NEW.raw_payload->>'scanner_score') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (NEW.raw_payload->>'scanner_score')::double precision END,
      NEW.evidence_quality_score::double precision
    );
  END IF;
  IF NEW.evidence_quality IS NULL THEN
    NEW.evidence_quality := NEW.evidence_quality_score;
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_alpha_leads_aliases_biu ON alpha_leads;
CREATE TRIGGER trg_alpha_leads_aliases_biu
  BEFORE INSERT OR UPDATE OF raw_payload, lead_type, evidence_quality_score, evidence_quality, company_name, scanner_type, scanner_run_id, market_context, score ON alpha_leads
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_alpha_leads_aliases();

CREATE OR REPLACE FUNCTION wolfy_sync_scanner_results_aliases()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.scanner_run_id IS NULL THEN
    NEW.scanner_run_id := NEW.run_id;
  END IF;
  IF NEW.status IS NULL THEN
    IF NEW.liquidity_pass IS FALSE THEN
      NEW.status := 'filtered';
    ELSE
      NEW.status := 'observed';
    END IF;
  END IF;
  IF NEW.company_name IS NULL THEN
    NEW.company_name := COALESCE(NEW.notes->>'company_name', NEW.notes->>'company');
  END IF;
  IF NEW.scanner_type IS NULL THEN
    NEW.scanner_type := COALESCE(NEW.notes->>'scanner_type', NEW.notes->>'signal', NEW.notes->>'lead_type');
  END IF;
  IF NEW.signal IS NULL THEN
    NEW.signal := COALESCE(NEW.notes->>'signal', NEW.notes->>'scanner_type', NEW.scanner_type);
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_scanner_results_aliases_biu ON scanner_results;
CREATE TRIGGER trg_scanner_results_aliases_biu
  BEFORE INSERT OR UPDATE OF run_id, scanner_run_id, liquidity_pass, status, notes, company_name, scanner_type, signal ON scanner_results
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_scanner_results_aliases();

-- EOD run-ledger compatibility for read-only ops probes. Canonical EOD code
-- uses runs.started/runs.finished; diagnostics often expect started_at /
-- completed_at and a feature-run projection.
CREATE TABLE IF NOT EXISTS runs (
  id serial PRIMARY KEY,
  job text,
  started timestamptz,
  finished timestamptz,
  status text,
  detail jsonb
);
ALTER TABLE runs ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
UPDATE runs
SET started_at=COALESCE(started_at, started),
    completed_at=COALESCE(completed_at, finished)
WHERE started_at IS NULL OR completed_at IS NULL;

CREATE OR REPLACE FUNCTION wolfy_sync_runs_aliases()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.started_at IS NULL THEN
    NEW.started_at := NEW.started;
  END IF;
  IF NEW.completed_at IS NULL THEN
    NEW.completed_at := NEW.finished;
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_runs_aliases_biu ON runs;
CREATE TRIGGER trg_runs_aliases_biu
  BEFORE INSERT OR UPDATE OF started, finished, started_at, completed_at ON runs
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_runs_aliases();

DROP VIEW IF EXISTS eod_feature_runs;
CREATE VIEW eod_feature_runs AS
SELECT
  id,
  job,
  started,
  finished,
  started_at,
  completed_at,
  status,
  detail,
  NULLIF(detail->>'bars_loaded', '')::integer AS bars_loaded,
  NULLIF(detail->>'feature_rows_upserted', '')::integer AS feature_rows_upserted,
  NULLIF(detail->>'tickers_processed', '')::integer AS tickers_processed
FROM runs
WHERE job LIKE 'eod-%' OR job LIKE 'feature%';

-- Universe compatibility for read-only ops probes. Canonical tables are
-- universe_symbols and universe_backfill_targets; diagnostics sometimes use
-- shorter names/aliases such as universe.enabled or targets.enabled.
ALTER TABLE universe_backfill_targets ADD COLUMN IF NOT EXISTS enabled BOOLEAN;
ALTER TABLE universe_backfill_targets ADD COLUMN IF NOT EXISTS wolfy_tier TEXT;
ALTER TABLE universe_backfill_targets ADD COLUMN IF NOT EXISTS tier_source TEXT;
ALTER TABLE universe_backfill_targets ADD COLUMN IF NOT EXISTS backfill_priority INTEGER;
ALTER TABLE universe_backfill_targets ADD COLUMN IF NOT EXISTS backfill_enabled BOOLEAN;
UPDATE universe_backfill_targets
SET enabled=active
WHERE enabled IS NULL;
UPDATE universe_backfill_targets
SET wolfy_tier=tier
WHERE wolfy_tier IS NULL;
UPDATE universe_backfill_targets
SET tier_source=source
WHERE tier_source IS NULL;
UPDATE universe_backfill_targets
SET backfill_priority=priority
WHERE backfill_priority IS NULL;
UPDATE universe_backfill_targets
SET backfill_enabled=COALESCE(enabled, active, true)
WHERE backfill_enabled IS NULL;

CREATE OR REPLACE FUNCTION wolfy_sync_universe_backfill_targets_aliases()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.enabled IS NULL THEN
    NEW.enabled := COALESCE(NEW.active, true);
  END IF;
  IF NEW.active IS NULL THEN
    NEW.active := COALESCE(NEW.enabled, true);
  END IF;
  IF NEW.wolfy_tier IS NULL THEN
    NEW.wolfy_tier := NEW.tier;
  END IF;
  IF NEW.tier IS NULL THEN
    NEW.tier := NEW.wolfy_tier;
  END IF;
  IF NEW.tier_source IS NULL THEN
    NEW.tier_source := NEW.source;
  END IF;
  IF NEW.source IS NULL THEN
    NEW.source := NEW.tier_source;
  END IF;
  IF NEW.backfill_priority IS NULL THEN
    NEW.backfill_priority := NEW.priority;
  END IF;
  IF NEW.priority IS NULL THEN
    NEW.priority := NEW.backfill_priority;
  END IF;
  IF NEW.backfill_enabled IS NULL THEN
    NEW.backfill_enabled := COALESCE(NEW.enabled, NEW.active, true);
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_universe_backfill_targets_aliases_biu ON universe_backfill_targets;
CREATE TRIGGER trg_universe_backfill_targets_aliases_biu
  BEFORE INSERT OR UPDATE OF active, enabled, tier, wolfy_tier, source, tier_source, priority, backfill_priority, backfill_enabled ON universe_backfill_targets
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_universe_backfill_targets_aliases();

DROP VIEW IF EXISTS universe;
CREATE VIEW universe AS
SELECT
  symbol,
  name,
  source,
  sector,
  is_etf,
  last_seen,
  active,
  active AS enabled,
  wolfy_tier,
  wolfy_tier AS tier,
  tier_source,
  backfill_priority,
  backfill_enabled,
  tier_notes
FROM universe_symbols;
