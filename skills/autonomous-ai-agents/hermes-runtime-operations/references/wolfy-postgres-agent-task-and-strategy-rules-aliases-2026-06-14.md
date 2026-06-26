# Wolfy Postgres alias drift: `agent_tasks.error_message` and `strategy_rules.ticker` (2026-06-14)

## Trigger
Mike ops saw ad-hoc/Jonah diagnostic probes fail against the live Wolfy Postgres DB because they expected common compatibility names that the canonical schema/view did not expose:

- `agent_tasks.error_message` in blocked-task triage queries.
- `strategy_rules.ticker` in legacy strategy-rule probes.

This is schema drift, not a market-analysis issue. Fix it with non-destructive aliases and preserve it in init/autorepair layers.

## Safe repair pattern

1. Add nullable compatibility aliases and backfill only from existing canonical values:

```sql
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS error_message TEXT;
UPDATE agent_tasks
SET summary=description
WHERE summary IS NULL AND description IS NOT NULL;
UPDATE agent_tasks
SET error_message=COALESCE(error_message, summary, description)
WHERE status='blocked' AND error_message IS NULL;
```

2. Preserve future blocked-task reasons in the helper API:

```python
UPDATE agent_tasks
SET status='blocked', updated_at=now(),
    description=concat_ws(E'\n', description, %s::text),
    error_message=COALESCE(error_message, %s::text)
WHERE id=%s
```

3. If adding/removing columns in a compatibility view, do **not** rely on `CREATE OR REPLACE VIEW`; Postgres rejects column-list changes with errors like `cannot change name of view column` or `cannot drop columns from view`. For read-only compatibility views with no dependent production writes, use:

```sql
DROP VIEW IF EXISTS strategy_rules;
CREATE VIEW strategy_rules AS
SELECT
  id::bigint AS id,
  name,
  NULL::text AS ticker,
  name AS rule_name,
  status,
  ...
FROM strategies
UNION ALL
SELECT
  ('1000000000'::bigint + source_id::bigint) AS id,
  btrim(regexp_replace(split_part(content, E'\n', 1), '^Rule:\s*', '')) AS name,
  NULL::text AS ticker,
  btrim(regexp_replace(split_part(content, E'\n', 1), '^Rule:\s*', '')) AS rule_name,
  ...
FROM knowledge_chunks
WHERE source_table='sqlite.strategy_rules' AND source_id ~ '^[0-9]+$';
```

4. Add/update a trigger so future blocked rows fill the alias automatically:

```sql
CREATE OR REPLACE FUNCTION wolfy_sync_agent_tasks_aliases()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.summary IS NULL THEN
    NEW.summary := NEW.description;
  END IF;
  IF NEW.status = 'blocked' AND NEW.error_message IS NULL THEN
    NEW.error_message := COALESCE(NEW.summary, NEW.description);
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_agent_tasks_aliases_biu ON agent_tasks;
CREATE TRIGGER trg_agent_tasks_aliases_biu
  BEFORE INSERT OR UPDATE OF description, summary, error_message, status ON agent_tasks
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_agent_tasks_aliases();
```

## Preservation layers

Patch all layers that can recreate or overwrite the fix:

- `/root/.hermes/wolfy/postgres_init.sql`
- `/root/.hermes/scripts/mike_safe_autorepair.py` — canonical source for the script-only repair loop
- `/root/.hermes/wolfy/mike_safe_autorepair.py`
- `/root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py`
- `/root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py`
- `/root/.hermes/wolfy/wolfy_agent_coordination.py` for helper API behavior

Important: if the local Wolfy autorepair script self-syncs from `/root/.hermes/scripts/mike_safe_autorepair.py`, patch the global canonical copy too. Otherwise the next autorepair run can overwrite the Wolfy-local fix.

## Verification

Run real, non-destructive checks:

```bash
/root/.hermes/wolfy/check_postgres_requirements.py
psql -d wolfy -v ON_ERROR_STOP=1 -c "
  select id,agent_name,task_type,title,status,error_message,updated_at
  from agent_tasks where status='blocked' order by updated_at desc limit 5;
  select id,name,ticker,rule_name,status from strategy_rules limit 3;
  select count(*) total, count(embedding) embedded from knowledge_chunks;
"
psql -d wolfy -v ON_ERROR_STOP=1 -c "
  SELECT count(*) AS stale_started_runs
  FROM agent_runs WHERE status='started' AND started_at < now() - interval '2 hours';
  SELECT count(*) AS synthetic_blocked_tasks
  FROM agent_tasks
  WHERE status='blocked' AND title='Smoke blocked task'
    AND source_fingerprint LIKE 'smoke-block-%';
  SELECT count(*) AS duplicate_claim_noise
  FROM agent_runs
  WHERE error_message='duplicate-or-already-claimed'
    AND started_at > now() - interval '24 hours';
"
python3 /root/.hermes/wolfy/embed_knowledge_chunks.py
python3 /root/.hermes/wolfy/cleanup_stale_agent_coordination.py
python3 /root/.hermes/wolfy/capture_usage_snapshot.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py  # second run should be silent
```

Healthy outputs from the original repair included: `758/758` embedded chunks, zero stale started runs, zero synthetic blocked tasks, zero duplicate claim noise, and a silent second autorepair run.
