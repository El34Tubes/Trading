# Wolfy Postgres `knowledge_chunks.title` compatibility alias (2026-06-15)

## Trigger
Mike ops saw recurring ad-hoc/LLM-authored diagnostics query:

```sql
select id, source_table, source_id, title, created_at, left(content, ...) from knowledge_chunks ...
```

Canonical `knowledge_chunks` did not have a top-level `title`; titles lived on `agent_artifacts.title` or occasionally in `knowledge_chunks.metadata` as `title` / `source_title`. The live failure was `ERROR: column "title" does not exist`.

## Safe repair pattern
Use a non-destructive nullable alias rather than changing canonical write paths:

```sql
ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS title TEXT;

UPDATE knowledge_chunks kc
SET title = COALESCE(
  kc.title,
  kc.metadata->>'title',
  kc.metadata->>'source_title',
  aa.title,
  kc.source_table || ':' || kc.source_id
)
FROM agent_artifacts aa
WHERE kc.artifact_id = aa.id
  AND kc.title IS NULL;

UPDATE knowledge_chunks
SET title = COALESCE(title, metadata->>'title', metadata->>'source_title', source_table || ':' || source_id)
WHERE title IS NULL;
```

Add/preserve a trigger so future rows keep the alias populated:

```sql
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
```

## Preservation layers
Patch both:

- `/root/.hermes/wolfy/postgres_init.sql`
- `/root/.hermes/wolfy/mike_safe_autorepair.py` inside `ensure_postgres_compatibility_aliases()`

Run autorepair twice; the second run should be silent.

## Verification
Use real commands:

```bash
psql -d wolfy -c "select count(*) total, count(title) with_title from knowledge_chunks"
psql -d wolfy -c "select id,source_table,source_id,title,created_at,left(content,60) as snippet from knowledge_chunks order by created_at desc limit 3"
psql -d wolfy -c "select tgname from pg_trigger where tgrelid='knowledge_chunks'::regclass and not tgisinternal"
python3 /root/.hermes/wolfy/mike_safe_autorepair.py
python3 /root/.hermes/wolfy/mike_safe_autorepair.py
```

Expected after repair: all chunks have `title`, trigger `trg_knowledge_chunks_aliases_biu` exists, and second autorepair run emits no output.
