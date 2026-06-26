# Wolfy `agent_artifacts.source_final_url` compatibility alias (2026-06-20)

## Trigger
Jonah/Wolfy ad-hoc Postgres probes queried `agent_artifacts.source_final_url`, while the canonical schema only stored `agent_artifacts.source_url`. This created repeated scratch-probe failures even though durable artifact writes were healthy.

## Safe fix pattern
Use the usual non-destructive compatibility-alias approach:

```sql
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
```

Preserve the same block in both:

- `/root/.hermes/wolfy/postgres_init.sql`
- canonical `/root/.hermes/scripts/mike_safe_autorepair.py`, then run it so it syncs Wolfy/Mike/Clerky copies.

## Verification
Run canonical autorepair twice; the second run should be silent. Then verify:

```bash
psql -d wolfy -X -v ON_ERROR_STOP=1 -c \
  "select count(*) total, count(source_url) source_url_count, count(source_final_url) source_final_url_count from agent_artifacts;"
psql -d wolfy -X -v ON_ERROR_STOP=1 -c \
  "select id,artifact_type,title,source_fingerprint,source_url,source_final_url from agent_artifacts order by id desc limit 1;"
python3 -m py_compile \
  /root/.hermes/scripts/mike_safe_autorepair.py \
  /root/.hermes/wolfy/mike_safe_autorepair.py \
  /root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py \
  /root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py
```

Also run the standard silent no-agent smokes (`wolfy_embed_knowledge_chunks.py`, `wolfy_cleanup_stale_agent_coordination.py`, `wolfy_capture_usage_snapshot.py`) and a context-smoke side-effect check when relevant.

## Pitfall
If an old scratch probe still fails with psycopg placeholder errors such as `only '%s', '%b', '%t' are allowed as placeholders` because it used raw `'%ARM%'` inside a Python SQL string, classify that as an ad-hoc probe bug, not durable schema drift. Verify the equivalent query directly with `psql` before adding more aliases.
