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

CREATE TABLE IF NOT EXISTS agent_runs (
    id BIGSERIAL PRIMARY KEY,
    agent_name TEXT NOT NULL,
    role TEXT NOT NULL,
    job_id TEXT,
    task_id BIGINT REFERENCES agent_tasks(id),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ,
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

CREATE TABLE IF NOT EXISTS agent_artifacts (
    id BIGSERIAL PRIMARY KEY,
    agent_name TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    source_url TEXT,
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

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id BIGSERIAL PRIMARY KEY,
    artifact_id BIGINT REFERENCES agent_artifacts(id) ON DELETE CASCADE,
    source_table TEXT,
    source_id TEXT,
    chunk_index INTEGER NOT NULL DEFAULT 0,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    embedding vector(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(source_table, source_id, chunk_index)
);

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
    recommendation_id TEXT NOT NULL,
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
