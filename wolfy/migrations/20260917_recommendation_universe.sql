-- Immutable point-in-time market-cap/bar evidence and recommendation universe.
BEGIN;

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

COMMIT;
