-- Immutable point-in-time source observations for stock identity and veto risks.
BEGIN;

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

COMMIT;
