-- Wolfy/Jonah/Sentinel Postgres scale-up schema
-- PostgreSQL 16 + pgvector foundation. SQLite remains the current source of truth until migration is complete.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS loop_metrics (
    id BIGSERIAL PRIMARY KEY,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id BIGINT NULL,
    category TEXT NOT NULL,
    metric_key TEXT NOT NULL,
    metric_value NUMERIC,
    metric_text TEXT,
    notes TEXT
);
-- Compatibility aliases for older read-only ops probes. Canonical fields are
-- captured_at/metric_key/metric_value.
ALTER TABLE loop_metrics ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
ALTER TABLE loop_metrics ADD COLUMN IF NOT EXISTS metric_name TEXT;
ALTER TABLE loop_metrics ADD COLUMN IF NOT EXISTS value_numeric NUMERIC;
UPDATE loop_metrics
SET created_at = COALESCE(created_at, captured_at),
    metric_name = COALESCE(metric_name, metric_key),
    value_numeric = COALESCE(value_numeric, metric_value)
WHERE created_at IS NULL OR metric_name IS NULL OR value_numeric IS NULL;
CREATE OR REPLACE FUNCTION wolfy_sync_loop_metrics_aliases()
RETURNS trigger AS $$
BEGIN
  NEW.created_at := COALESCE(NEW.created_at, NEW.captured_at, now());
  NEW.metric_name := COALESCE(NEW.metric_name, NEW.metric_key);
  NEW.value_numeric := COALESCE(NEW.value_numeric, NEW.metric_value);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_loop_metrics_aliases ON loop_metrics;
CREATE TRIGGER trg_loop_metrics_aliases
  BEFORE INSERT OR UPDATE OF captured_at, metric_key, metric_value, created_at, metric_name, value_numeric
  ON loop_metrics
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_loop_metrics_aliases();
CREATE INDEX IF NOT EXISTS idx_loop_metrics_key_time ON loop_metrics(metric_key, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_loop_metrics_name_time ON loop_metrics(metric_name, created_at DESC);

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
-- Compatibility alias for prompts/scripts that ask for task instructions.
-- Canonical task prose remains description.
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS instructions TEXT;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS instruction TEXT;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS definition_of_done TEXT;
-- Compatibility aliases for optimizer/ops probes that expect verification
-- metadata as top-level task columns. Canonical storage may still be in
-- metadata/payload JSONB or definition_of_done.
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS verification_result TEXT;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS commit_hash TEXT;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS error_message TEXT;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS blocker_reason TEXT;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS payload JSONB;
-- These provenance columns are referenced by the compatibility payload refresh
-- below, so they must exist on a clean database as well as an upgraded one.
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS source_table TEXT;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS source_id TEXT;
-- Compatibility alias for ad-hoc/read-only probes that expect task metadata.
-- Canonical structured task detail remains payload.
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS metadata JSONB;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS agent TEXT;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS assigned_agent TEXT;
-- Compatibility alias for ad-hoc/read-only ops probes that expect claimed_by.
-- Canonical assignment remains agent_tasks.agent_name / assigned_agent.
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS claimed_by TEXT;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS type TEXT;
-- Compatibility alias for ad-hoc/read-only ops probes that expect one ticker.
-- Canonical task symbols remain agent_tasks.ticker_symbols (text[]).
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS ticker TEXT;
-- Compatibility alias for read-only ops probes that expect task_id.
-- Canonical task primary key remains agent_tasks.id.
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS task_id BIGINT;
-- Compatibility aliases for read-only/ad-hoc provenance probes.
-- Canonical task identity remains id/source_fingerprint; durable provenance uses source_table/source_id.
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS source_table TEXT;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS source_id TEXT;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS source TEXT;
UPDATE agent_tasks
SET agent=agent_name
WHERE agent IS NULL;
UPDATE agent_tasks
SET assigned_agent=agent_name
WHERE assigned_agent IS NULL;
UPDATE agent_tasks
SET claimed_by=COALESCE(assigned_agent, agent, agent_name)
WHERE claimed_by IS NULL;
UPDATE agent_tasks
SET type=task_type
WHERE type IS NULL;
UPDATE agent_tasks
SET task_id=id
WHERE task_id IS NULL;
UPDATE agent_tasks
SET ticker=COALESCE(ticker, payload->>'ticker', payload->>'symbol', ticker_symbols[1])
WHERE ticker IS NULL;
UPDATE agent_tasks
SET source_table=COALESCE(source_table, payload->>'source_table', 'agent_tasks'),
    source_id=COALESCE(source_id, payload->>'source_id', source_fingerprint, id::text),
    source=COALESCE(source, payload->>'source', source_table, 'agent_tasks')
WHERE source_table IS NULL OR source_id IS NULL OR source IS NULL;
UPDATE agent_tasks
SET summary=description
WHERE summary IS NULL AND description IS NOT NULL;
UPDATE agent_tasks
SET instructions=description
WHERE instructions IS NULL AND description IS NOT NULL;
UPDATE agent_tasks
SET instruction=COALESCE(instruction, instructions, description)
WHERE instruction IS NULL;
UPDATE agent_tasks
SET definition_of_done=COALESCE(definition_of_done, payload->>'definition_of_done')
WHERE definition_of_done IS NULL;
UPDATE agent_tasks
SET verification_result=COALESCE(verification_result, metadata->>'verification_result', payload->>'verification_result', definition_of_done)
WHERE verification_result IS NULL;
UPDATE agent_tasks
SET commit_hash=COALESCE(commit_hash, metadata->>'commit_hash', payload->>'commit_hash')
WHERE commit_hash IS NULL;
UPDATE agent_tasks
SET metadata=COALESCE(metadata, payload, '{}'::jsonb)
WHERE metadata IS NULL;
UPDATE agent_tasks
SET error_message=COALESCE(error_message, summary, description)
WHERE status='blocked' AND error_message IS NULL;
UPDATE agent_tasks
SET blocker_reason=COALESCE(blocker_reason, error_message, summary, description)
WHERE status='blocked' AND blocker_reason IS NULL;
UPDATE agent_tasks
SET payload = jsonb_strip_nulls(jsonb_build_object(
    'id', id,
    'task_id', task_id,
    'agent_name', agent_name,
    'agent', agent,
    'assigned_agent', assigned_agent,
    'claimed_by', claimed_by,
    'task_type', task_type,
    'type', type,
    'title', title,
    'description', description,
    'instructions', instructions,
    'instruction', instruction,
    'definition_of_done', definition_of_done,
    'status', status,
    'priority', priority,
    'source_fingerprint', source_fingerprint,
    'topic_tags', topic_tags,
    'ticker_symbols', ticker_symbols,
    'ticker', ticker,
    'depends_on', depends_on,
    'supersedes', supersedes,
    'created_at', created_at,
    'updated_at', updated_at,
    'summary', summary,
    'error_message', error_message,
    'blocker_reason', blocker_reason
))
WHERE payload IS NULL;
UPDATE agent_tasks
SET payload = jsonb_strip_nulls(payload || jsonb_build_object(
    'instruction', instruction,
    'definition_of_done', definition_of_done,
    'verification_result', verification_result,
    'commit_hash', commit_hash,
    'verified_at', verified_at,
    'error_message', error_message,
    'blocker_reason', blocker_reason,
    'source_table', source_table,
    'source_id', source_id,
    'source', source,
    'ticker', ticker,
    'metadata', metadata
))
WHERE payload IS NOT NULL
  AND (instruction IS NOT NULL OR definition_of_done IS NOT NULL OR verification_result IS NOT NULL OR commit_hash IS NOT NULL OR verified_at IS NOT NULL OR error_message IS NOT NULL OR blocker_reason IS NOT NULL OR source_table IS NOT NULL OR source_id IS NOT NULL OR source IS NOT NULL OR ticker IS NOT NULL OR metadata IS NOT NULL);

CREATE TABLE IF NOT EXISTS agent_runs (
    id BIGSERIAL PRIMARY KEY,
    agent_name TEXT NOT NULL,
    role TEXT NOT NULL,
    job_id TEXT,
    task_id BIGINT REFERENCES agent_tasks(id),
    run_id BIGINT,
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
-- Compatibility alias for read-only ops probes that expect run_id.
-- Canonical run primary key remains agent_runs.id.
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS run_id BIGINT;
UPDATE agent_runs SET run_id=id WHERE run_id IS NULL;
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
  legacy_id BIGINT UNIQUE,
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
  legacy_id BIGINT UNIQUE,
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
  risk_flags JSONB NOT NULL DEFAULT '[]',
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
ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS risk_flags JSONB NOT NULL DEFAULT '[]';
UPDATE alpha_leads
SET risk_flags = COALESCE(NULLIF(risk_flags, '[]'::jsonb), raw_payload->'risk_flags', suspicious_flags, raw_payload->'suspicious_flags', '[]'::jsonb)
WHERE risk_flags IS NULL OR risk_flags = '[]'::jsonb;
CREATE INDEX IF NOT EXISTS idx_pg_alpha_leads_ticker_status ON alpha_leads(ticker, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_pg_alpha_leads_quality ON alpha_leads(evidence_quality_score DESC, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_pg_alpha_leads_suspicious ON alpha_leads(suspicious_action, updated_at DESC);

CREATE TABLE IF NOT EXISTS alpha_lead_evidence (
  id BIGSERIAL PRIMARY KEY,
  legacy_id BIGINT UNIQUE,
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
  legacy_id BIGINT UNIQUE,
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

-- Preserve both historical identifiers across fresh and upgraded databases.
-- Older production tables use legacy_id; newer clean-schema drafts used
-- sqlite_id.  Add and synchronize both before any compatibility view reads
-- either name.  Unique indexes keep the import identity contract explicit.
ALTER TABLE alpha_search_reports ADD COLUMN IF NOT EXISTS legacy_id BIGINT;
ALTER TABLE alpha_search_reports ADD COLUMN IF NOT EXISTS sqlite_id BIGINT;
UPDATE alpha_search_reports
SET legacy_id=COALESCE(legacy_id, sqlite_id),
    sqlite_id=COALESCE(sqlite_id, legacy_id)
WHERE legacy_id IS NULL OR sqlite_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_alpha_search_reports_legacy_id ON alpha_search_reports(legacy_id) WHERE legacy_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_alpha_search_reports_sqlite_id ON alpha_search_reports(sqlite_id) WHERE sqlite_id IS NOT NULL;

ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS legacy_id BIGINT;
ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS sqlite_id BIGINT;
UPDATE alpha_leads
SET legacy_id=COALESCE(legacy_id, sqlite_id),
    sqlite_id=COALESCE(sqlite_id, legacy_id)
WHERE legacy_id IS NULL OR sqlite_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_alpha_leads_legacy_id ON alpha_leads(legacy_id) WHERE legacy_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_alpha_leads_sqlite_id ON alpha_leads(sqlite_id) WHERE sqlite_id IS NOT NULL;

ALTER TABLE alpha_lead_evidence ADD COLUMN IF NOT EXISTS legacy_id BIGINT;
ALTER TABLE alpha_lead_evidence ADD COLUMN IF NOT EXISTS sqlite_id BIGINT;
UPDATE alpha_lead_evidence
SET legacy_id=COALESCE(legacy_id, sqlite_id),
    sqlite_id=COALESCE(sqlite_id, legacy_id)
WHERE legacy_id IS NULL OR sqlite_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_alpha_lead_evidence_legacy_id ON alpha_lead_evidence(legacy_id) WHERE legacy_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_alpha_lead_evidence_sqlite_id ON alpha_lead_evidence(sqlite_id) WHERE sqlite_id IS NOT NULL;

ALTER TABLE alpha_handoffs ADD COLUMN IF NOT EXISTS legacy_id BIGINT;
ALTER TABLE alpha_handoffs ADD COLUMN IF NOT EXISTS sqlite_id BIGINT;
UPDATE alpha_handoffs
SET legacy_id=COALESCE(legacy_id, sqlite_id),
    sqlite_id=COALESCE(sqlite_id, legacy_id)
WHERE legacy_id IS NULL OR sqlite_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_alpha_handoffs_legacy_id ON alpha_handoffs(legacy_id) WHERE legacy_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_alpha_handoffs_sqlite_id ON alpha_handoffs(sqlite_id) WHERE sqlite_id IS NOT NULL;

CREATE OR REPLACE FUNCTION wolfy_sync_alpha_import_ids()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.legacy_id := COALESCE(NEW.legacy_id, NEW.sqlite_id);
  NEW.sqlite_id := COALESCE(NEW.sqlite_id, NEW.legacy_id);
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_alpha_search_reports_import_ids ON alpha_search_reports;
CREATE TRIGGER trg_alpha_search_reports_import_ids
  BEFORE INSERT OR UPDATE OF legacy_id, sqlite_id ON alpha_search_reports
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_alpha_import_ids();
DROP TRIGGER IF EXISTS trg_alpha_leads_import_ids ON alpha_leads;
CREATE TRIGGER trg_alpha_leads_import_ids
  BEFORE INSERT OR UPDATE OF legacy_id, sqlite_id ON alpha_leads
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_alpha_import_ids();
DROP TRIGGER IF EXISTS trg_alpha_lead_evidence_import_ids ON alpha_lead_evidence;
CREATE TRIGGER trg_alpha_lead_evidence_import_ids
  BEFORE INSERT OR UPDATE OF legacy_id, sqlite_id ON alpha_lead_evidence
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_alpha_import_ids();
DROP TRIGGER IF EXISTS trg_alpha_handoffs_import_ids ON alpha_handoffs;
CREATE TRIGGER trg_alpha_handoffs_import_ids
  BEFORE INSERT OR UPDATE OF legacy_id, sqlite_id ON alpha_handoffs
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_alpha_import_ids();

-- Non-destructive compatibility aliases for ad-hoc diagnostics and older helper probes.
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS result_summary TEXT;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS task_type TEXT;
UPDATE agent_runs SET completed_at=ended_at WHERE completed_at IS NULL AND ended_at IS NOT NULL;
UPDATE agent_runs SET finished_at=COALESCE(ended_at, completed_at) WHERE finished_at IS NULL AND (ended_at IS NOT NULL OR completed_at IS NOT NULL);
UPDATE agent_runs SET ended_at=COALESCE(ended_at, finished_at, completed_at) WHERE ended_at IS NULL AND (finished_at IS NOT NULL OR completed_at IS NOT NULL);
UPDATE agent_runs SET result_summary=summary WHERE result_summary IS NULL AND summary IS NOT NULL;
UPDATE agent_runs ar
SET task_type=at.task_type
FROM agent_tasks at
WHERE ar.task_id = at.id
  AND ar.task_type IS NULL;
UPDATE agent_runs ar
SET title=at.title
FROM agent_tasks at
WHERE ar.task_id = at.id
  AND ar.title IS NULL;

ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS source_table TEXT;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS source_id TEXT;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS source TEXT;
UPDATE agent_tasks
SET source_table=COALESCE(source_table, payload->>'source_table', 'agent_tasks'),
    source_id=COALESCE(source_id, payload->>'source_id', source_fingerprint, id::text),
    source=COALESCE(source, payload->>'source', source_table, 'agent_tasks')
WHERE source_table IS NULL OR source_id IS NULL OR source IS NULL;

-- Compatibility aliases for ad-hoc/read-only scanner run probes.
-- Canonical timing is run_time/completed_at and run size is derived from scanner_results.
ALTER TABLE scanner_runs ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE scanner_runs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE scanner_runs ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ;
ALTER TABLE scanner_runs ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE scanner_runs ADD COLUMN IF NOT EXISTS symbols_scanned INTEGER;
ALTER TABLE scanner_runs ADD COLUMN IF NOT EXISTS mode TEXT;
UPDATE scanner_runs sr
SET started_at=COALESCE(sr.started_at, sr.run_time),
    completed_at=COALESCE(sr.completed_at, sr.finished_at, sr.run_time),
    finished_at=COALESCE(sr.finished_at, sr.completed_at, sr.run_time),
    status=COALESCE(sr.status, CASE WHEN COALESCE(sr.finished_at, sr.completed_at, sr.run_time) IS NOT NULL THEN 'completed' ELSE 'started' END),
    mode=COALESCE(sr.mode, sr.data_source),
    symbols_scanned=COALESCE(sr.symbols_scanned, counts.result_count, 0)
FROM (
  SELECT run_id, count(*)::integer AS result_count
  FROM scanner_results
  GROUP BY run_id
) counts
WHERE sr.id = counts.run_id
  AND (sr.started_at IS NULL OR sr.completed_at IS NULL OR sr.finished_at IS NULL OR sr.status IS NULL OR sr.mode IS NULL OR sr.symbols_scanned IS NULL);
UPDATE scanner_runs
SET started_at=COALESCE(started_at, run_time),
    completed_at=COALESCE(completed_at, finished_at, run_time),
    finished_at=COALESCE(finished_at, completed_at, run_time),
    status=COALESCE(status, 'completed'),
    mode=COALESCE(mode, data_source),
    symbols_scanned=COALESCE(symbols_scanned, 0)
WHERE started_at IS NULL OR completed_at IS NULL OR finished_at IS NULL OR status IS NULL OR mode IS NULL OR symbols_scanned IS NULL;

ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS scanner_run_id BIGINT;
-- Common ticker/volume aliases used by Jonah ad-hoc research probes.
-- Canonical scanner columns remain ticker and avg_volume.
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS symbol TEXT;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS ticker_symbol TEXT;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS volume DOUBLE PRECISION;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS company_name TEXT;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS scanner_type TEXT;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS signal TEXT;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS metadata JSONB;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS trend_50_200 TEXT;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS pattern TEXT;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS pattern_flags JSONB;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS rs_spy_20d DOUBLE PRECISION;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS rs_qqq_20d DOUBLE PRECISION;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS rs_vs_spy_20d DOUBLE PRECISION;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS rs_vs_qqq_20d DOUBLE PRECISION;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS avg_volume_20d DOUBLE PRECISION;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS close_price DOUBLE PRECISION;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS as_of_date DATE;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS r1 DOUBLE PRECISION;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS rank_position INTEGER;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS setup_type TEXT;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS metrics JSONB;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS flags JSONB;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS raw JSONB;
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
    symbol=COALESCE(symbol, ticker),
    ticker_symbol=COALESCE(ticker_symbol, ticker),
    volume=COALESCE(volume, avg_volume),
    avg_volume_20d=COALESCE(avg_volume_20d, avg_volume),
    close_price=COALESCE(close_price, close),
    as_of_date=COALESCE(as_of_date, data_date),
    status=COALESCE(status, CASE WHEN liquidity_pass IS FALSE THEN 'filtered' ELSE 'observed' END),
    company_name=COALESCE(company_name, notes->>'company_name', notes->>'company'),
    scanner_type=COALESCE(scanner_type, notes->>'scanner_type', notes->>'signal', notes->>'lead_type'),
    signal=COALESCE(signal, notes->>'signal', notes->>'scanner_type', scanner_type),
    metadata=COALESCE(metadata, notes, '{}'::jsonb),
    trend_50_200=COALESCE(trend_50_200, trend_regime, notes->>'trend_50_200', notes->>'trend_regime'),
    pattern=COALESCE(pattern, gap_reversal_flag, notes->>'pattern', notes->>'gap_reversal_flag'),
    pattern_flags=COALESCE(
      pattern_flags,
      notes->'pattern_flags',
      jsonb_strip_nulls(jsonb_build_object(
        'pattern', COALESCE(pattern, gap_reversal_flag, notes->>'pattern', notes->>'gap_reversal_flag'),
        'gap_reversal_flag', gap_reversal_flag,
        'squeeze_flag', squeeze_flag,
        'trend_regime', trend_regime
      ))
    ),
    rs_spy_20=COALESCE(rs_spy_20, CASE WHEN (notes->>'rs_spy_20') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (notes->>'rs_spy_20')::double precision END),
    rs_qqq_20=COALESCE(rs_qqq_20, CASE WHEN (notes->>'rs_qqq_20') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (notes->>'rs_qqq_20')::double precision END),
    rs_spy_20d=COALESCE(rs_spy_20d, rs_spy_20, CASE WHEN (notes->>'rs_spy_20d') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (notes->>'rs_spy_20d')::double precision END),
    rs_qqq_20d=COALESCE(rs_qqq_20d, rs_qqq_20, CASE WHEN (notes->>'rs_qqq_20d') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (notes->>'rs_qqq_20d')::double precision END),
    rs_vs_spy_20d=COALESCE(rs_vs_spy_20d, rs_spy_20d, rs_spy_20, CASE WHEN (notes->>'rs_vs_spy_20d') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (notes->>'rs_vs_spy_20d')::double precision END),
    rs_vs_qqq_20d=COALESCE(rs_vs_qqq_20d, rs_qqq_20d, rs_qqq_20, CASE WHEN (notes->>'rs_vs_qqq_20d') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (notes->>'rs_vs_qqq_20d')::double precision END),
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
    gap_reversal_flag=COALESCE(gap_reversal_flag, notes->>'gap_reversal_flag'),
    setup_type=COALESCE(setup_type, signal, scanner_type, notes->>'setup_type', notes->>'signal'),
    metrics=COALESCE(metrics, metadata, notes, '{}'::jsonb),
    flags=COALESCE(flags, notes->'flags', pattern_flags, jsonb_strip_nulls(jsonb_build_object('pattern', pattern, 'gap_reversal_flag', gap_reversal_flag, 'squeeze_flag', squeeze_flag, 'trend_regime', trend_regime))),
    raw=COALESCE(raw, metadata, notes, '{}'::jsonb)
WHERE scanner_run_id IS NULL OR symbol IS NULL OR ticker_symbol IS NULL OR volume IS NULL OR status IS NULL OR company_name IS NULL OR scanner_type IS NULL OR signal IS NULL
   OR metadata IS NULL OR trend_50_200 IS NULL OR pattern IS NULL OR pattern_flags IS NULL OR rs_spy_20d IS NULL OR rs_qqq_20d IS NULL
   OR rs_vs_spy_20d IS NULL OR rs_vs_qqq_20d IS NULL OR avg_volume_20d IS NULL OR close_price IS NULL OR as_of_date IS NULL
   OR rs_spy_20 IS NULL OR rs_qqq_20 IS NULL OR breakout_20d_pct IS NULL OR volume_surge_1d_20 IS NULL
   OR volume_surge_5d_20 IS NULL OR volume_surge_1d_50 IS NULL OR volume_surge_5d_50 IS NULL
   OR atr_pct IS NULL OR squeeze_ratio IS NULL OR squeeze_flag IS NULL OR liquidity_spread_proxy IS NULL
   OR trend_regime IS NULL OR rank_reasons IS NULL OR gap_reversal_flag IS NULL OR setup_type IS NULL OR metrics IS NULL OR flags IS NULL OR raw IS NULL;

ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS company_name TEXT;
ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS scanner_type TEXT;
ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS scanner_run_id BIGINT;
ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS market_context JSONB;
ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS score DOUBLE PRECISION;
ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS evidence_quality NUMERIC(5,3);
ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS rationale TEXT;
ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS evidence TEXT;
-- Compatibility alias for ad-hoc/read-only ops probes that expect metadata.
-- Canonical detail remains alpha_leads.raw_payload.
ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS metadata JSONB;
-- Compatibility alias for ad-hoc/read-only probes that expect the historical
-- suspicious_activity JSON object. Canonical storage remains suspicious_action
-- + suspicious_flags, with optional raw_payload.suspicious_activity detail.
ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS suspicious_activity JSONB;
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
    evidence=COALESCE(evidence, raw_payload->>'evidence', raw_payload->>'rationale', raw_payload->>'summary', thesis, title),
    score=COALESCE(score,
      CASE WHEN (raw_payload->>'score') ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (raw_payload->>'score')::double precision END,
      CASE WHEN (raw_payload->>'scanner_score') ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (raw_payload->>'scanner_score')::double precision END,
      evidence_quality_score::double precision),
    evidence_quality=COALESCE(evidence_quality, evidence_quality_score),
    metadata=COALESCE(metadata, raw_payload, '{}'::jsonb),
    suspicious_activity=COALESCE(
      suspicious_activity,
      raw_payload->'suspicious_activity',
      jsonb_build_object('recommended_action', suspicious_action, 'flags', suspicious_flags)
    )
WHERE company_name IS NULL OR scanner_type IS NULL OR scanner_run_id IS NULL OR market_context IS NULL OR score IS NULL OR evidence_quality IS NULL OR rationale IS NULL OR summary IS NULL OR evidence IS NULL OR metadata IS NULL OR suspicious_activity IS NULL;

ALTER TABLE recommendation_reviews
  ALTER COLUMN recommendation_id TYPE BIGINT USING recommendation_id::bigint;

DROP VIEW IF EXISTS alpha_search_leads;
CREATE VIEW alpha_search_leads AS
SELECT
  id, legacy_id, legacy_id AS sqlite_id, report_id, created_at, updated_at, ticker, lead_type, title,
  thesis, rationale, summary,
  COALESCE(evidence, rationale, summary, thesis, raw_payload->>'evidence', raw_payload->>'rationale', title) AS evidence,
  status, evidence_quality_score AS score,
  evidence_quality_score, evidence_quality, evidence_count, highest_source_quality,
  suspicious_action, suspicious_flags, suspicious_activity, risk_flags, catalyst_window, social_context,
  filing_context, insider_context, complete_ticket, recommendation_id,
  next_research_question, company_name, scanner_type, scanner_run_id, market_context,
  raw_payload, source_fingerprint,
  'alpha_leads'::text AS source_table,
  id::text AS source_id
FROM alpha_leads;

-- Read-only compatibility view for ad-hoc probes that still query the older
-- SQLite-era strategy_rules name. Canonical EOD strategy state lives in
-- strategies; archived learning rules live in knowledge_chunks.
-- Compatibility aliases for ad-hoc/read-only ops probes that query
-- strategies.metadata or strategies.description directly. Canonical strategy
-- parameters remain params and canonical prose remains notes; aliases mirror
-- those fields non-destructively for probe compatibility.
ALTER TABLE strategies ADD COLUMN IF NOT EXISTS metadata JSONB;
ALTER TABLE strategies ADD COLUMN IF NOT EXISTS description TEXT;
UPDATE strategies
SET metadata = COALESCE(metadata, params, '{}'::jsonb)
WHERE metadata IS NULL;
UPDATE strategies
SET description = notes
WHERE description IS NULL AND notes IS NOT NULL;

CREATE OR REPLACE FUNCTION wolfy_sync_strategies_aliases()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.metadata IS NULL THEN
    NEW.metadata := COALESCE(NEW.params, '{}'::jsonb);
  END IF;
  NEW.description := COALESCE(NEW.notes, NEW.description);
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_strategies_aliases_biu ON strategies;
CREATE TRIGGER trg_strategies_aliases_biu
  BEFORE INSERT OR UPDATE OF params, metadata, notes, description ON strategies
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_strategies_aliases();

DROP VIEW IF EXISTS strategy_rules;
CREATE VIEW strategy_rules AS
SELECT
  id::bigint AS id,
  name,
  name AS title,
  NULL::text AS ticker,
  NULL::text AS ticker_symbol,
  name AS rule_name,
  status,
  status AS scope,
  status AS implementation_status,
  setup_type AS rule_type,
  setup_type AS timeframe,
  setup_type AS setup_type,
  ARRAY[]::text[] AS ticker_symbols,
  ARRAY[]::text[] AS ticker_universe,
  ARRAY[]::text[] AS tickers,
  ARRAY[setup_type, status]::text[] AS topic_tags,
  ARRAY[setup_type, status]::text[] AS universe_tags,
  ARRAY[setup_type]::text[] AS asset_classes,
  ARRAY[setup_type, status]::text[] AS universe,
  notes AS description,
  notes AS summary,
  notes AS body,
  notes AS rule_body,
  notes AS reasons,
  COALESCE(params, '{}'::jsonb) AS metadata,
  COALESCE(params->>'source','postgres.strategies') AS source_basis,
  (status IN ('approved','candidate')) AS enabled,
  (status IN ('approved','candidate')) AS is_enabled,
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
  NULL::text AS ticker_symbol,
  btrim(regexp_replace(split_part(content, E'\n', 1), '^Rule:\s*', '')) AS rule_name,
  'active'::text AS status,
  'active'::text AS scope,
  'active'::text AS implementation_status,
  NULLIF(btrim(regexp_replace(split_part(content, E'\n', 2), '^Type:\s*', '')), '') AS rule_type,
  NULLIF(btrim(regexp_replace(split_part(content, E'\n', 2), '^Type:\s*', '')), '') AS timeframe,
  NULLIF(btrim(regexp_replace(split_part(content, E'\n', 2), '^Type:\s*', '')), '') AS setup_type,
  ARRAY[]::text[] AS ticker_symbols,
  ARRAY[]::text[] AS ticker_universe,
  ARRAY[]::text[] AS tickers,
  ARRAY_REMOVE(ARRAY['postgres.strategy_rules', NULLIF(btrim(regexp_replace(split_part(content, E'\n', 2), '^Type:\s*', '')), '')], NULL)::text[] AS topic_tags,
  ARRAY_REMOVE(ARRAY['postgres.strategy_rules', NULLIF(btrim(regexp_replace(split_part(content, E'\n', 2), '^Type:\s*', '')), '')], NULL)::text[] AS universe_tags,
  ARRAY_REMOVE(ARRAY[NULLIF(btrim(regexp_replace(split_part(content, E'\n', 2), '^Type:\s*', '')), '')], NULL)::text[] AS asset_classes,
  ARRAY_REMOVE(ARRAY['postgres.strategy_rules', NULLIF(btrim(regexp_replace(split_part(content, E'\n', 2), '^Type:\s*', '')), '')], NULL)::text[] AS universe,
  btrim(regexp_replace(regexp_replace(content, E'^Rule:[^\n]*\nType:[^\n]*\nDescription:\s*', ''), E'\n+', ' ', 'g')) AS description,
  btrim(regexp_replace(regexp_replace(content, E'^Rule:[^\n]*\nType:[^\n]*\nDescription:\s*', ''), E'\n+', ' ', 'g')) AS summary,
  btrim(regexp_replace(regexp_replace(content, E'^Rule:[^\n]*\nType:[^\n]*\nDescription:\s*', ''), E'\n+', ' ', 'g')) AS body,
  btrim(regexp_replace(regexp_replace(content, E'^Rule:[^\n]*\nType:[^\n]*\nDescription:\s*', ''), E'\n+', ' ', 'g')) AS rule_body,
  btrim(regexp_replace(regexp_replace(content, E'^Rule:[^\n]*\nType:[^\n]*\nDescription:\s*', ''), E'\n+', ' ', 'g')) AS reasons,
  metadata AS metadata,
  'postgres.strategy_rules'::text AS source_basis,
  true AS enabled,
  true AS is_enabled,
  true AS is_active,
  created_at AS created_at,
  created_at AS updated_at,
  'equity_etf_process'::text AS asset_class,
  NULLIF(btrim(regexp_replace(split_part(content, E'\n', 2), '^Type:\s*', '')), '') AS category,
  source_id AS source_id,
  btrim(regexp_replace(regexp_replace(content, E'^Rule:[^\n]*\nType:[^\n]*\nDescription:\s*', ''), E'\n+', ' ', 'g')) AS rule_text
FROM knowledge_chunks
WHERE source_table='postgres.strategy_rules' AND source_id ~ '^[0-9]+$';

CREATE OR REPLACE FUNCTION wolfy_sync_agent_runs_aliases()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.finished_at IS NULL THEN
    NEW.finished_at := COALESCE(NEW.ended_at, NEW.completed_at);
  END IF;
  IF NEW.completed_at IS NULL THEN
    NEW.completed_at := COALESCE(NEW.ended_at, NEW.finished_at);
  END IF;
  IF NEW.ended_at IS NULL THEN
    NEW.ended_at := COALESCE(NEW.completed_at, NEW.finished_at);
  END IF;
  IF NEW.result_summary IS NULL THEN
    NEW.result_summary := NEW.summary;
  END IF;
  IF NEW.summary IS NULL THEN
    NEW.summary := NEW.result_summary;
  END IF;
  IF (NEW.task_type IS NULL OR NEW.title IS NULL) AND NEW.task_id IS NOT NULL THEN
    SELECT COALESCE(NEW.task_type, at.task_type), COALESCE(NEW.title, at.title)
    INTO NEW.task_type, NEW.title
    FROM agent_tasks at
    WHERE at.id = NEW.task_id;
  END IF;
  IF NEW.run_id IS NULL THEN
    NEW.run_id := NEW.id;
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_agent_runs_aliases_biu ON agent_runs;
CREATE TRIGGER trg_agent_runs_aliases_biu
  BEFORE INSERT OR UPDATE OF task_id, task_type, title, ended_at, completed_at, finished_at, summary, result_summary, run_id ON agent_runs
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_agent_runs_aliases();

CREATE OR REPLACE FUNCTION wolfy_sync_scanner_runs_aliases()
RETURNS trigger AS $$
BEGIN
  IF NEW.started_at IS NULL THEN
    NEW.started_at := NEW.run_time;
  END IF;
  IF NEW.completed_at IS NULL THEN
    NEW.completed_at := COALESCE(NEW.finished_at, NEW.run_time);
  END IF;
  IF NEW.finished_at IS NULL THEN
    NEW.finished_at := COALESCE(NEW.completed_at, NEW.run_time);
  END IF;
  IF NEW.status IS NULL THEN
    NEW.status := CASE WHEN COALESCE(NEW.finished_at, NEW.completed_at, NEW.run_time) IS NOT NULL THEN 'completed' ELSE 'started' END;
  END IF;
  IF NEW.symbols_scanned IS NULL THEN
    NEW.symbols_scanned := 0;
  END IF;
  IF NEW.mode IS NULL THEN
    NEW.mode := NEW.data_source;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_scanner_runs_aliases_biu ON scanner_runs;
CREATE TRIGGER trg_scanner_runs_aliases_biu
  BEFORE INSERT OR UPDATE OF run_time, started_at, completed_at, finished_at, status, symbols_scanned, data_source, mode ON scanner_runs
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_scanner_runs_aliases();

CREATE OR REPLACE FUNCTION wolfy_sync_agent_tasks_aliases()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.type IS NULL THEN
  NEW.type := NEW.task_type;
  END IF;
  IF NEW.task_id IS NULL THEN
  NEW.task_id := NEW.id;
  END IF;
  IF NEW.ticker IS NULL THEN
  NEW.ticker := COALESCE(NEW.payload->>'ticker', NEW.payload->>'symbol', NEW.ticker_symbols[1]);
  END IF;
  IF NEW.agent IS NULL THEN
    NEW.agent := NEW.agent_name;
  END IF;
  IF NEW.assigned_agent IS NULL THEN
    NEW.assigned_agent := NEW.agent_name;
  END IF;
  IF NEW.claimed_by IS NULL THEN
    NEW.claimed_by := COALESCE(NEW.assigned_agent, NEW.agent, NEW.agent_name);
  END IF;
  IF NEW.summary IS NULL THEN
    NEW.summary := NEW.description;
  END IF;
  IF NEW.instructions IS NULL THEN
    NEW.instructions := NEW.description;
  END IF;
  IF NEW.instruction IS NULL THEN
    NEW.instruction := COALESCE(NEW.instructions, NEW.description);
  END IF;
  IF NEW.status = 'blocked' AND NEW.error_message IS NULL THEN
    NEW.error_message := COALESCE(NEW.blocker_reason, NEW.summary, NEW.description);
  END IF;
  IF NEW.status = 'blocked' AND NEW.blocker_reason IS NULL THEN
    NEW.blocker_reason := COALESCE(NEW.error_message, NEW.summary, NEW.description);
  END IF;
  IF NEW.metadata IS NULL THEN
    NEW.metadata := COALESCE(NEW.payload, '{}'::jsonb);
  END IF;
  IF NEW.verification_result IS NULL THEN
    NEW.verification_result := COALESCE(NEW.metadata->>'verification_result', NEW.payload->>'verification_result', NEW.definition_of_done);
  END IF;
  IF NEW.commit_hash IS NULL THEN
    NEW.commit_hash := COALESCE(NEW.metadata->>'commit_hash', NEW.payload->>'commit_hash');
  END IF;
  IF NEW.payload IS NULL THEN
  NEW.payload := jsonb_strip_nulls(jsonb_build_object(
  'id', NEW.id,
  'task_id', NEW.task_id,
  'agent_name', NEW.agent_name,
  'agent', NEW.agent,
  'assigned_agent', NEW.assigned_agent,
  'claimed_by', NEW.claimed_by,
  'task_type', NEW.task_type,
  'type', NEW.type,
  'title', NEW.title,
  'description', NEW.description,
  'instructions', NEW.instructions,
  'instruction', NEW.instruction,
  'definition_of_done', NEW.definition_of_done,
  'verification_result', NEW.verification_result,
  'commit_hash', NEW.commit_hash,
  'verified_at', NEW.verified_at,
  'status', NEW.status,
  'priority', NEW.priority,
  'source_fingerprint', NEW.source_fingerprint,
  'topic_tags', NEW.topic_tags,
  'ticker_symbols', NEW.ticker_symbols,
  'ticker', NEW.ticker,
  'depends_on', NEW.depends_on,
  'supersedes', NEW.supersedes,
  'created_at', NEW.created_at,
  'updated_at', NEW.updated_at,
  'summary', NEW.summary,
  'error_message', NEW.error_message,
  'blocker_reason', NEW.blocker_reason,
  'source_table', NEW.source_table,
  'source_id', NEW.source_id,
  'source', NEW.source,
  'ticker', NEW.ticker,
  'metadata', NEW.metadata
  ));
  ELSE
  NEW.payload := jsonb_strip_nulls(NEW.payload || jsonb_build_object(
  'instruction', NEW.instruction,
  'definition_of_done', NEW.definition_of_done,
  'verification_result', NEW.verification_result,
  'commit_hash', NEW.commit_hash,
  'verified_at', NEW.verified_at,
  'claimed_by', NEW.claimed_by,
  'error_message', NEW.error_message,
  'blocker_reason', NEW.blocker_reason,
  'source_table', NEW.source_table,
  'source_id', NEW.source_id,
  'source', NEW.source,
  'ticker', NEW.ticker,
  'metadata', NEW.metadata
  ));
  END IF;
  IF NEW.source_table IS NULL THEN
  NEW.source_table := COALESCE(NEW.payload->>'source_table', 'agent_tasks');
  END IF;
  IF NEW.source_id IS NULL THEN
  NEW.source_id := COALESCE(NEW.payload->>'source_id', NEW.source_fingerprint, NEW.id::text);
  END IF;
  IF NEW.source IS NULL THEN
  NEW.source := COALESCE(NEW.payload->>'source', NEW.source_table, 'agent_tasks');
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_agent_tasks_aliases_biu ON agent_tasks;
CREATE TRIGGER trg_agent_tasks_aliases_biu
  BEFORE INSERT OR UPDATE OF task_id, task_type, type, agent_name, agent, assigned_agent, claimed_by, description, instructions, instruction, definition_of_done, verification_result, commit_hash, verified_at, summary, error_message, blocker_reason, status, payload, metadata, source_table, source_id, source, ticker, ticker_symbols ON agent_tasks
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
  IF NEW.evidence IS NULL THEN
    NEW.evidence := COALESCE(NEW.raw_payload->>'evidence', NEW.raw_payload->>'rationale', NEW.raw_payload->>'summary', NEW.thesis, NEW.title);
  END IF;
  IF NEW.metadata IS NULL THEN
    NEW.metadata := COALESCE(NEW.raw_payload, '{}'::jsonb);
  END IF;
  IF NEW.suspicious_activity IS NULL THEN
    NEW.suspicious_activity := COALESCE(
      NEW.raw_payload->'suspicious_activity',
      jsonb_build_object('recommended_action', NEW.suspicious_action, 'flags', NEW.suspicious_flags)
    );
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_alpha_leads_aliases_biu ON alpha_leads;
CREATE TRIGGER trg_alpha_leads_aliases_biu
  BEFORE INSERT OR UPDATE OF raw_payload, lead_type, evidence_quality_score, evidence_quality, evidence, company_name, scanner_type, scanner_run_id, market_context, score, risk_flags, suspicious_flags, suspicious_activity, metadata ON alpha_leads
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_alpha_leads_aliases();

CREATE OR REPLACE FUNCTION wolfy_sync_scanner_results_aliases()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.scanner_run_id IS NULL THEN
    NEW.scanner_run_id := NEW.run_id;
  END IF;
  IF NEW.symbol IS NULL THEN
    NEW.symbol := NEW.ticker;
  END IF;
  IF NEW.ticker_symbol IS NULL THEN
    NEW.ticker_symbol := NEW.ticker;
  END IF;
  IF NEW.volume IS NULL THEN
    NEW.volume := NEW.avg_volume;
  END IF;
  IF NEW.avg_volume_20d IS NULL THEN
    NEW.avg_volume_20d := NEW.avg_volume;
  END IF;
  IF NEW.close_price IS NULL THEN
    NEW.close_price := NEW.close;
  END IF;
  IF NEW.as_of_date IS NULL THEN
    NEW.as_of_date := NEW.data_date;
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
  IF NEW.setup_type IS NULL THEN
    NEW.setup_type := COALESCE(NEW.signal, NEW.scanner_type, NEW.notes->>'setup_type', NEW.notes->>'signal');
  END IF;
  IF NEW.metadata IS NULL THEN
    NEW.metadata := COALESCE(NEW.notes, '{}'::jsonb);
  END IF;
  IF NEW.metrics IS NULL THEN
    NEW.metrics := COALESCE(NEW.metadata, NEW.notes, '{}'::jsonb);
  END IF;
  IF NEW.trend_50_200 IS NULL THEN
    NEW.trend_50_200 := COALESCE(NEW.trend_regime, NEW.notes->>'trend_50_200', NEW.notes->>'trend_regime');
  END IF;
  IF NEW.pattern IS NULL THEN
    NEW.pattern := COALESCE(NEW.gap_reversal_flag, NEW.notes->>'pattern', NEW.notes->>'gap_reversal_flag');
  END IF;
  IF NEW.pattern_flags IS NULL THEN
    NEW.pattern_flags := COALESCE(
      NEW.notes->'pattern_flags',
      jsonb_strip_nulls(jsonb_build_object(
        'pattern', NEW.pattern,
        'gap_reversal_flag', NEW.gap_reversal_flag,
        'squeeze_flag', NEW.squeeze_flag,
        'trend_regime', NEW.trend_regime
      ))
    );
  END IF;
  IF NEW.flags IS NULL THEN
    NEW.flags := COALESCE(NEW.notes->'flags', NEW.pattern_flags, '{}'::jsonb);
  END IF;
  IF NEW.raw IS NULL THEN
    NEW.raw := COALESCE(NEW.metadata, NEW.notes, '{}'::jsonb);
  END IF;
  IF NEW.rs_spy_20d IS NULL THEN
    NEW.rs_spy_20d := NEW.rs_spy_20;
  END IF;
  IF NEW.rs_qqq_20d IS NULL THEN
    NEW.rs_qqq_20d := NEW.rs_qqq_20;
  END IF;
  IF NEW.rs_vs_spy_20d IS NULL THEN
    NEW.rs_vs_spy_20d := COALESCE(NEW.rs_spy_20d, NEW.rs_spy_20);
  END IF;
  IF NEW.rs_vs_qqq_20d IS NULL THEN
    NEW.rs_vs_qqq_20d := COALESCE(NEW.rs_qqq_20d, NEW.rs_qqq_20);
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_scanner_results_aliases_biu ON scanner_results;
CREATE TRIGGER trg_scanner_results_aliases_biu
  BEFORE INSERT OR UPDATE OF run_id, scanner_run_id, ticker, symbol, ticker_symbol, avg_volume, avg_volume_20d, close, close_price, data_date, as_of_date, volume, liquidity_pass, status, notes, company_name, scanner_type, signal, setup_type, metadata, metrics, trend_regime, trend_50_200, gap_reversal_flag, pattern, pattern_flags, flags, raw, squeeze_flag, rs_spy_20, rs_qqq_20, rs_spy_20d, rs_qqq_20d, rs_vs_spy_20d, rs_vs_qqq_20d ON scanner_results
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
  detail jsonb,
  source text
);
ALTER TABLE runs ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS source TEXT;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS rows_written INTEGER;
UPDATE runs
SET started_at=COALESCE(started_at, started),
    completed_at=COALESCE(completed_at, finished),
    ended_at=COALESCE(ended_at, completed_at, finished),
    source=COALESCE(source, NULLIF(detail->>'source', '')),
    rows_written=COALESCE(
      rows_written,
      CASE WHEN (detail->>'rows_written') ~ '^[0-9]+$' THEN (detail->>'rows_written')::integer END,
      CASE WHEN (detail->>'rows_upserted') ~ '^[0-9]+$' THEN (detail->>'rows_upserted')::integer END,
      CASE WHEN (detail->>'feature_rows_upserted') ~ '^[0-9]+$' THEN (detail->>'feature_rows_upserted')::integer END
    )
WHERE started_at IS NULL OR completed_at IS NULL OR ended_at IS NULL OR source IS NULL OR rows_written IS NULL;

CREATE OR REPLACE FUNCTION wolfy_sync_runs_aliases()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.started_at IS NULL THEN
    NEW.started_at := NEW.started;
  END IF;
  IF NEW.completed_at IS NULL THEN
    NEW.completed_at := NEW.finished;
  END IF;
  IF NEW.ended_at IS NULL THEN
    NEW.ended_at := COALESCE(NEW.completed_at, NEW.finished);
  END IF;
  IF NEW.source IS NULL THEN
    NEW.source := NULLIF(NEW.detail->>'source', '');
  END IF;
  IF NEW.rows_written IS NULL THEN
    NEW.rows_written := COALESCE(
      CASE WHEN (NEW.detail->>'rows_written') ~ '^[0-9]+$' THEN (NEW.detail->>'rows_written')::integer END,
      CASE WHEN (NEW.detail->>'rows_upserted') ~ '^[0-9]+$' THEN (NEW.detail->>'rows_upserted')::integer END,
      CASE WHEN (NEW.detail->>'feature_rows_upserted') ~ '^[0-9]+$' THEN (NEW.detail->>'feature_rows_upserted')::integer END
    );
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_runs_aliases_biu ON runs;
CREATE TRIGGER trg_runs_aliases_biu
  BEFORE INSERT OR UPDATE OF started, finished, started_at, completed_at, ended_at, detail, source, rows_written ON runs
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
  ended_at,
  status,
  source,
  rows_written,
  detail,
  CASE WHEN (detail->>'bars_loaded') ~ '^[0-9]+$' THEN (detail->>'bars_loaded')::integer END AS bars_loaded,
  CASE WHEN (detail->>'feature_rows_upserted') ~ '^[0-9]+$' THEN (detail->>'feature_rows_upserted')::integer END AS feature_rows_upserted,
  CASE WHEN (detail->>'tickers_processed') ~ '^[0-9]+$' THEN (detail->>'tickers_processed')::integer END AS tickers_processed
FROM runs
WHERE job LIKE 'eod%' OR job LIKE 'feature%';

-- Storage/ops metric compatibility for read-only diagnostics. Canonical
-- watchdog rows use captured_at/root_used_pct/etc.; ad-hoc probes sometimes
-- expect generic metric_name/metric_value/category/created_at columns.
CREATE TABLE IF NOT EXISTS system_metrics (
  id BIGSERIAL PRIMARY KEY,
  captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  hermes_bytes BIGINT,
  wolfy_bytes BIGINT,
  retired_db_bytes BIGINT,
  root_used_pct DOUBLE PRECISION,
  root_avail_bytes BIGINT,
  cron_job_count INTEGER,
  notes TEXT
);
ALTER TABLE system_metrics ADD COLUMN IF NOT EXISTS metric_name TEXT;
ALTER TABLE system_metrics ADD COLUMN IF NOT EXISTS metric_value DOUBLE PRECISION;
ALTER TABLE system_metrics ADD COLUMN IF NOT EXISTS category TEXT;
ALTER TABLE system_metrics ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
UPDATE system_metrics
SET metric_name=COALESCE(metric_name, 'storage.snapshot'),
    metric_value=COALESCE(metric_value, root_used_pct),
    category=COALESCE(category, 'storage'),
    created_at=COALESCE(created_at, captured_at)
WHERE metric_name IS NULL OR metric_value IS NULL OR category IS NULL OR created_at IS NULL;

CREATE OR REPLACE FUNCTION wolfy_sync_system_metrics_aliases()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.created_at IS NULL THEN
    NEW.created_at := NEW.captured_at;
  END IF;
  IF NEW.captured_at IS NULL THEN
    NEW.captured_at := NEW.created_at;
  END IF;
  IF NEW.metric_name IS NULL THEN
    NEW.metric_name := 'storage.snapshot';
  END IF;
  IF NEW.metric_value IS NULL THEN
    NEW.metric_value := NEW.root_used_pct;
  END IF;
  IF NEW.category IS NULL THEN
    NEW.category := 'storage';
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_system_metrics_aliases_biu ON system_metrics;
CREATE TRIGGER trg_system_metrics_aliases_biu
  BEFORE INSERT OR UPDATE OF captured_at, created_at, root_used_pct, metric_name, metric_value, category ON system_metrics
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_system_metrics_aliases();

-- Universe compatibility for read-only ops probes. Canonical tables are
-- universe_symbols and universe_backfill_targets; diagnostics sometimes use
-- shorter names/aliases such as universe.enabled or targets.enabled. Define the
-- canonical target relation first so this schema also applies to a clean test DB.
CREATE TABLE IF NOT EXISTS universe_backfill_targets (
  symbol TEXT PRIMARY KEY,
  tier TEXT NOT NULL,
  source TEXT NOT NULL,
  name TEXT,
  priority INTEGER NOT NULL,
  active BOOLEAN NOT NULL DEFAULT true,
  reason TEXT NOT NULL,
  selected_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_universe_backfill_targets_tier_priority
  ON universe_backfill_targets(tier, priority);
ALTER TABLE universe_symbols ADD COLUMN IF NOT EXISTS wolfy_tier TEXT;
ALTER TABLE universe_symbols ADD COLUMN IF NOT EXISTS tier_source TEXT;
ALTER TABLE universe_symbols ADD COLUMN IF NOT EXISTS backfill_priority INTEGER;
ALTER TABLE universe_symbols ADD COLUMN IF NOT EXISTS backfill_enabled BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE universe_symbols ADD COLUMN IF NOT EXISTS tier_notes TEXT;
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
-- Task 3: atomic, serialized daily evaluation ledger migration.
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

-- Immutable read-only option chain provenance and ticker-bound evaluations.
CREATE TABLE IF NOT EXISTS option_chain_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    provider TEXT NOT NULL,
    source_url TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    market_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    chain JSONB NOT NULL CHECK (jsonb_typeof(chain) = 'array'),
    paper_only BOOLEAN NOT NULL DEFAULT TRUE CHECK (paper_only),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
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

CREATE TABLE IF NOT EXISTS option_structure_evaluations (
    id BIGSERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    signal_dt DATE NOT NULL,
    strategy_name TEXT NOT NULL,
    underlying_price NUMERIC NOT NULL,
    technical_target NUMERIC NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL,
    chain JSONB NOT NULL,
    evaluation JSONB NOT NULL,
    selected_structure TEXT,
    snapshot_id TEXT NOT NULL REFERENCES option_chain_snapshots(snapshot_id),
    decision_at TIMESTAMPTZ NOT NULL,
    source_signal_id BIGINT,
    run_id BIGINT,
    paper_only BOOLEAN NOT NULL DEFAULT TRUE CHECK (paper_only),
    no_live_execution BOOLEAN NOT NULL DEFAULT TRUE CHECK (no_live_execution),
    broker_order_submitted BOOLEAN NOT NULL DEFAULT FALSE CHECK (NOT broker_order_submitted),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (ticker, signal_dt, strategy_name)
);
ALTER TABLE option_structure_evaluations
    ADD COLUMN IF NOT EXISTS snapshot_id TEXT REFERENCES option_chain_snapshots(snapshot_id),
    ADD COLUMN IF NOT EXISTS decision_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS source_signal_id BIGINT,
    ADD COLUMN IF NOT EXISTS run_id BIGINT;
CREATE INDEX IF NOT EXISTS idx_option_structure_evaluations_signal
    ON option_structure_evaluations(signal_dt DESC, ticker);
CREATE INDEX IF NOT EXISTS idx_option_structure_evaluations_snapshot
    ON option_structure_evaluations(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_option_chain_snapshots_ticker_available
    ON option_chain_snapshots(ticker, available_at DESC);

-- Canonical active recommendation identity. Populated upgrades use the matching
-- 20260917_recommendation_uniqueness.sql migration, which reports duplicate
-- keys and never rewrites or deletes legacy rows.
LOCK TABLE recommendations IN SHARE ROW EXCLUSIVE MODE;
DO $$
DECLARE
    duplicate_keys JSONB;
BEGIN
    SELECT jsonb_agg(
               jsonb_build_object(
                   'ticker', ticker,
                   'signal_dt', signal_dt,
                   'strategy_name', strategy_name,
                   'row_count', row_count,
                   'recommendation_ids', recommendation_ids
               ) ORDER BY ticker, signal_dt, strategy_name
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
            'duplicate active recommendation identities block schema bootstrap: %',
            duplicate_keys;
    END IF;
END
$$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_experimental_paper_recommendation_signal
    ON recommendations (
        ticker, (notes->>'signal_dt'), (notes->>'strategy_name')
    )
    WHERE recommendation_type = 'experimental_defined_risk_option'
      AND status IN ('paper_candidate', 'paper_logged')
      AND notes->>'signal_dt' IS NOT NULL
      AND notes->>'strategy_name' IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_recommendation_signal
    ON recommendations (
        ticker, (notes->>'signal_dt'), (notes->>'strategy_name')
    )
    WHERE status IN ('paper_candidate', 'paper_logged')
      AND notes->>'signal_dt' IS NOT NULL
      AND notes->>'strategy_name' IS NOT NULL;

-- Immutable point-in-time source observations for stock identity and veto risks.
CREATE TABLE IF NOT EXISTS security_identity_observations (
    observation_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL CHECK (ticker = upper(ticker) AND btrim(ticker) <> ''),
    provider TEXT NOT NULL CHECK (btrim(provider) <> ''),
    source_url TEXT NOT NULL CHECK (btrim(source_url) <> ''),
    effective_from TIMESTAMPTZ NOT NULL,
    effective_to TIMESTAMPTZ,
    observed_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    security_type TEXT,
    locale TEXT,
    market TEXT,
    primary_exchange TEXT,
    currency TEXT,
    issuer_country TEXT,
    active BOOLEAN,
    delisted_at TIMESTAMPTZ,
    product_type TEXT,
    leveraged BOOLEAN NOT NULL,
    inverse BOOLEAN NOT NULL,
    single_stock_product BOOLEAN NOT NULL,
    raw_source JSONB NOT NULL CHECK (jsonb_typeof(raw_source) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (effective_to IS NULL OR effective_to > effective_from),
    CHECK (available_at >= observed_at)
);
CREATE INDEX IF NOT EXISTS idx_security_identity_asof
    ON security_identity_observations(ticker, effective_from DESC, available_at DESC);

CREATE TABLE IF NOT EXISTS security_risk_observations (
    observation_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL CHECK (ticker = upper(ticker) AND btrim(ticker) <> ''),
    risk_type TEXT NOT NULL CHECK (risk_type IN ('manipulation', 'government_interference')),
    decision TEXT NOT NULL CHECK (decision IN ('clear', 'veto')),
    reason_code TEXT NOT NULL CHECK (btrim(reason_code) <> ''),
    source TEXT NOT NULL CHECK (btrim(source) <> ''),
    evidence JSONB NOT NULL CHECK (jsonb_typeof(evidence) = 'object'),
    effective_from TIMESTAMPTZ NOT NULL,
    effective_to TIMESTAMPTZ,
    available_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (effective_to IS NULL OR effective_to > effective_from)
);
CREATE INDEX IF NOT EXISTS idx_security_risk_asof
    ON security_risk_observations(ticker, effective_from DESC, available_at DESC);

CREATE TABLE IF NOT EXISTS security_denylist_observations (
    observation_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL CHECK (ticker = upper(ticker) AND btrim(ticker) <> ''),
    reason_code TEXT NOT NULL CHECK (btrim(reason_code) <> ''),
    source TEXT NOT NULL CHECK (btrim(source) <> ''),
    effective_from TIMESTAMPTZ NOT NULL,
    effective_to TIMESTAMPTZ,
    available_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (effective_to IS NULL OR effective_to > effective_from)
);
CREATE INDEX IF NOT EXISTS idx_security_denylist_asof
    ON security_denylist_observations(ticker, effective_from DESC, available_at DESC);

CREATE OR REPLACE FUNCTION wolfy_reject_security_observation_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'security observations are append-only';
END
$$;
DROP TRIGGER IF EXISTS trg_security_identity_observations_immutable
    ON security_identity_observations;
CREATE TRIGGER trg_security_identity_observations_immutable
    BEFORE UPDATE OR DELETE ON security_identity_observations
    FOR EACH ROW EXECUTE FUNCTION wolfy_reject_security_observation_mutation();
DROP TRIGGER IF EXISTS trg_security_risk_observations_immutable
    ON security_risk_observations;
CREATE TRIGGER trg_security_risk_observations_immutable
    BEFORE UPDATE OR DELETE ON security_risk_observations
    FOR EACH ROW EXECUTE FUNCTION wolfy_reject_security_observation_mutation();
DROP TRIGGER IF EXISTS trg_security_denylist_observations_immutable
    ON security_denylist_observations;
CREATE TRIGGER trg_security_denylist_observations_immutable
    BEFORE UPDATE OR DELETE ON security_denylist_observations
    FOR EACH ROW EXECUTE FUNCTION wolfy_reject_security_observation_mutation();

-- Immutable point-in-time market-cap/bar evidence and recommendation universe.
CREATE TABLE IF NOT EXISTS security_market_cap_observations (
    observation_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL CHECK (ticker = upper(ticker) AND btrim(ticker) <> ''),
    market_cap NUMERIC NOT NULL CHECK (market_cap > 0),
    provider TEXT NOT NULL CHECK (btrim(provider) <> ''),
    source_url TEXT NOT NULL CHECK (btrim(source_url) <> ''),
    effective_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    raw_source JSONB NOT NULL CHECK (jsonb_typeof(raw_source) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_security_market_cap_asof
    ON security_market_cap_observations(ticker, effective_at DESC, available_at DESC);
CREATE TABLE IF NOT EXISTS adjusted_daily_bar_observations (
    observation_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL CHECK (ticker = upper(ticker) AND btrim(ticker) <> ''),
    session DATE NOT NULL,
    close NUMERIC NOT NULL CHECK (close > 0),
    volume BIGINT NOT NULL CHECK (volume >= 0),
    provider TEXT NOT NULL CHECK (btrim(provider) <> ''),
    source_url TEXT NOT NULL CHECK (btrim(source_url) <> ''),
    available_at TIMESTAMPTZ NOT NULL,
    adjusted BOOLEAN NOT NULL CHECK (adjusted),
    raw_source JSONB NOT NULL CHECK (jsonb_typeof(raw_source) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (ticker, session, provider)
);
CREATE INDEX IF NOT EXISTS idx_adjusted_daily_bar_asof
    ON adjusted_daily_bar_observations(ticker, session DESC, available_at DESC);
CREATE TABLE IF NOT EXISTS recommendation_universe_snapshots (
    snapshot_id UUID PRIMARY KEY,
    signal_dt DATE NOT NULL,
    decision_at TIMESTAMPTZ NOT NULL,
    policy_version TEXT NOT NULL CHECK (btrim(policy_version) <> ''),
    source_fingerprint TEXT NOT NULL CHECK (source_fingerprint ~ '^[0-9a-f]{64}$'),
    included_count INTEGER NOT NULL CHECK (included_count >= 0),
    excluded_count INTEGER NOT NULL CHECK (excluded_count >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (signal_dt, decision_at, policy_version, source_fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_recommendation_universe_lookup
    ON recommendation_universe_snapshots(signal_dt, policy_version, decision_at DESC);
CREATE TABLE IF NOT EXISTS recommendation_universe_members (
    snapshot_id UUID NOT NULL REFERENCES recommendation_universe_snapshots(snapshot_id),
    ticker TEXT NOT NULL CHECK (ticker = upper(ticker) AND btrim(ticker) <> ''),
    sector TEXT NOT NULL CHECK (btrim(sector) <> ''),
    included BOOLEAN NOT NULL,
    reason_codes TEXT[] NOT NULL CHECK (cardinality(reason_codes) > 0),
    identity_observation_ids TEXT[] NOT NULL,
    risk_observation_ids TEXT[] NOT NULL,
    denylist_observation_ids TEXT[] NOT NULL,
    market_cap_observation_id TEXT,
    market_cap NUMERIC,
    bar_observation_ids TEXT[] NOT NULL,
    close NUMERIC,
    average_dollar_volume NUMERIC,
    source_evidence JSONB NOT NULL CHECK (jsonb_typeof(source_evidence) = 'object'),
    facts_hash TEXT NOT NULL CHECK (facts_hash ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_id, ticker),
    CHECK ((included AND reason_codes = ARRAY['eligible_mid_small_us_common_stock']::TEXT[]) OR NOT included)
);
CREATE INDEX IF NOT EXISTS idx_recommendation_universe_included
    ON recommendation_universe_members(snapshot_id, ticker) WHERE included;
CREATE OR REPLACE FUNCTION wolfy_reject_universe_observation_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'recommendation universe evidence is append-only';
END
$$;
DROP TRIGGER IF EXISTS trg_security_market_cap_observations_immutable
    ON security_market_cap_observations;
CREATE TRIGGER trg_security_market_cap_observations_immutable
    BEFORE UPDATE OR DELETE ON security_market_cap_observations
    FOR EACH ROW EXECUTE FUNCTION wolfy_reject_universe_observation_mutation();
DROP TRIGGER IF EXISTS trg_adjusted_daily_bar_observations_immutable
    ON adjusted_daily_bar_observations;
CREATE TRIGGER trg_adjusted_daily_bar_observations_immutable
    BEFORE UPDATE OR DELETE ON adjusted_daily_bar_observations
    FOR EACH ROW EXECUTE FUNCTION wolfy_reject_universe_observation_mutation();
DROP TRIGGER IF EXISTS trg_recommendation_universe_snapshots_immutable
    ON recommendation_universe_snapshots;
CREATE TRIGGER trg_recommendation_universe_snapshots_immutable
    BEFORE UPDATE OR DELETE ON recommendation_universe_snapshots
    FOR EACH ROW EXECUTE FUNCTION wolfy_reject_universe_observation_mutation();
DROP TRIGGER IF EXISTS trg_recommendation_universe_members_immutable
    ON recommendation_universe_members;
CREATE TRIGGER trg_recommendation_universe_members_immutable
    BEFORE UPDATE OR DELETE ON recommendation_universe_members
    FOR EACH ROW EXECUTE FUNCTION wolfy_reject_universe_observation_mutation();

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

-- Separate setup/underlying outcomes from exact-option expression outcomes.
ALTER TABLE recommendation_outcomes
    ADD COLUMN IF NOT EXISTS outcome_type TEXT NOT NULL DEFAULT 'underlying_setup';
DO $$
DECLARE duplicate_row RECORD;
BEGIN
    SELECT paper_trade_id, count(*) AS row_count INTO duplicate_row
      FROM recommendation_outcomes
     WHERE paper_trade_id IS NOT NULL
     GROUP BY paper_trade_id HAVING count(*) > 1
     ORDER BY paper_trade_id LIMIT 1;
    IF FOUND THEN
        RAISE EXCEPTION 'instrument outcomes bootstrap aborted: paper trade % has % underlying outcomes',
            duplicate_row.paper_trade_id, duplicate_row.row_count;
    END IF;
END
$$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_underlying_outcome_paper_trade
    ON recommendation_outcomes(paper_trade_id) WHERE paper_trade_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS option_outcomes (
    id BIGSERIAL PRIMARY KEY,
    recommendation_id TEXT NOT NULL,
    paper_trade_id TEXT NOT NULL UNIQUE,
    option_evaluation_id BIGINT NOT NULL REFERENCES option_structure_evaluations(id),
    entry_snapshot_id TEXT NOT NULL REFERENCES option_chain_snapshots(snapshot_id),
    exit_snapshot_id TEXT REFERENCES option_chain_snapshots(snapshot_id),
    expression TEXT NOT NULL CHECK (expression IN ('long_call', 'call_debit_spread')),
    status TEXT NOT NULL CHECK (status = 'closed'),
    exit_reason TEXT NOT NULL CHECK (btrim(exit_reason) <> ''),
    expiration DATE NOT NULL,
    entry_value NUMERIC NOT NULL CHECK (entry_value >= 0 AND entry_value NOT IN ('NaN'::NUMERIC, 'Infinity'::NUMERIC, '-Infinity'::NUMERIC)),
    exit_value NUMERIC NOT NULL CHECK (exit_value >= 0 AND exit_value NOT IN ('NaN'::NUMERIC, 'Infinity'::NUMERIC, '-Infinity'::NUMERIC)),
    max_loss NUMERIC NOT NULL CHECK (max_loss > 0 AND max_loss NOT IN ('NaN'::NUMERIC, 'Infinity'::NUMERIC, '-Infinity'::NUMERIC)),
    pnl NUMERIC NOT NULL CHECK (pnl >= -max_loss AND pnl NOT IN ('NaN'::NUMERIC, 'Infinity'::NUMERIC, '-Infinity'::NUMERIC)),
    return_on_risk NUMERIC NOT NULL CHECK (return_on_risk NOT IN ('NaN'::NUMERIC, 'Infinity'::NUMERIC, '-Infinity'::NUMERIC)),
    quote_at TIMESTAMPTZ,
    notes JSONB NOT NULL CHECK (jsonb_typeof(notes) = 'object'),
    paper_only BOOLEAN NOT NULL DEFAULT TRUE CHECK (paper_only),
    no_live_execution BOOLEAN NOT NULL DEFAULT TRUE CHECK (no_live_execution),
    broker_order_submitted BOOLEAN NOT NULL DEFAULT FALSE CHECK (NOT broker_order_submitted),
    graded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_option_outcomes_recommendation
    ON option_outcomes(recommendation_id, graded_at DESC);
CREATE INDEX IF NOT EXISTS idx_option_outcomes_evaluation
    ON option_outcomes(option_evaluation_id);

COMMIT;
