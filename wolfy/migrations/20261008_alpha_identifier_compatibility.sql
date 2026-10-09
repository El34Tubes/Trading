-- Preserve both historical SQLite import identifiers across clean and populated
-- Wolfy Alpha Search schemas. Older production tables use legacy_id; a later
-- bootstrap draft used sqlite_id. Keep both names synchronized for compatibility.

BEGIN;

ALTER TABLE alpha_search_reports ADD COLUMN IF NOT EXISTS legacy_id BIGINT;
ALTER TABLE alpha_search_reports ADD COLUMN IF NOT EXISTS sqlite_id BIGINT;
UPDATE alpha_search_reports
SET legacy_id=COALESCE(legacy_id, sqlite_id),
    sqlite_id=COALESCE(sqlite_id, legacy_id)
WHERE legacy_id IS NULL OR sqlite_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_alpha_search_reports_legacy_id
    ON alpha_search_reports(legacy_id) WHERE legacy_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_alpha_search_reports_sqlite_id
    ON alpha_search_reports(sqlite_id) WHERE sqlite_id IS NOT NULL;

ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS legacy_id BIGINT;
ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS sqlite_id BIGINT;
UPDATE alpha_leads
SET legacy_id=COALESCE(legacy_id, sqlite_id),
    sqlite_id=COALESCE(sqlite_id, legacy_id)
WHERE legacy_id IS NULL OR sqlite_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_alpha_leads_legacy_id
    ON alpha_leads(legacy_id) WHERE legacy_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_alpha_leads_sqlite_id
    ON alpha_leads(sqlite_id) WHERE sqlite_id IS NOT NULL;

ALTER TABLE alpha_lead_evidence ADD COLUMN IF NOT EXISTS legacy_id BIGINT;
ALTER TABLE alpha_lead_evidence ADD COLUMN IF NOT EXISTS sqlite_id BIGINT;
UPDATE alpha_lead_evidence
SET legacy_id=COALESCE(legacy_id, sqlite_id),
    sqlite_id=COALESCE(sqlite_id, legacy_id)
WHERE legacy_id IS NULL OR sqlite_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_alpha_lead_evidence_legacy_id
    ON alpha_lead_evidence(legacy_id) WHERE legacy_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_alpha_lead_evidence_sqlite_id
    ON alpha_lead_evidence(sqlite_id) WHERE sqlite_id IS NOT NULL;

ALTER TABLE alpha_handoffs ADD COLUMN IF NOT EXISTS legacy_id BIGINT;
ALTER TABLE alpha_handoffs ADD COLUMN IF NOT EXISTS sqlite_id BIGINT;
UPDATE alpha_handoffs
SET legacy_id=COALESCE(legacy_id, sqlite_id),
    sqlite_id=COALESCE(sqlite_id, legacy_id)
WHERE legacy_id IS NULL OR sqlite_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_alpha_handoffs_legacy_id
    ON alpha_handoffs(legacy_id) WHERE legacy_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_alpha_handoffs_sqlite_id
    ON alpha_handoffs(sqlite_id) WHERE sqlite_id IS NOT NULL;

DO $$
DECLARE
  relation_name TEXT;
  has_conflict BOOLEAN;
BEGIN
  FOREACH relation_name IN ARRAY ARRAY['alpha_search_reports', 'alpha_leads', 'alpha_lead_evidence', 'alpha_handoffs']
  LOOP
    EXECUTE format(
      'SELECT EXISTS (SELECT 1 FROM %I WHERE legacy_id IS NOT NULL AND sqlite_id IS NOT NULL AND legacy_id IS DISTINCT FROM sqlite_id)',
      relation_name
    ) INTO has_conflict;
    IF has_conflict THEN
      RAISE EXCEPTION 'conflicting legacy_id/sqlite_id values in %', relation_name;
    END IF;
  END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION wolfy_sync_alpha_import_ids()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.legacy_id IS NOT NULL AND NEW.sqlite_id IS NOT NULL
       AND NEW.legacy_id IS DISTINCT FROM NEW.sqlite_id THEN
      RAISE EXCEPTION 'conflicting alpha import identifiers: legacy_id %, sqlite_id %', NEW.legacy_id, NEW.sqlite_id;
    END IF;
    NEW.legacy_id := COALESCE(NEW.legacy_id, NEW.sqlite_id);
    NEW.sqlite_id := COALESCE(NEW.sqlite_id, NEW.legacy_id);
    RETURN NEW;
  END IF;

  IF NEW.legacy_id IS DISTINCT FROM OLD.legacy_id
     AND NEW.sqlite_id IS NOT DISTINCT FROM OLD.sqlite_id THEN
    NEW.sqlite_id := NEW.legacy_id;
  ELSIF NEW.sqlite_id IS DISTINCT FROM OLD.sqlite_id
        AND NEW.legacy_id IS NOT DISTINCT FROM OLD.legacy_id THEN
    NEW.legacy_id := NEW.sqlite_id;
  ELSIF NEW.legacy_id IS DISTINCT FROM NEW.sqlite_id THEN
    RAISE EXCEPTION 'conflicting alpha import identifier update: legacy_id %, sqlite_id %', NEW.legacy_id, NEW.sqlite_id;
  END IF;
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

COMMIT;
