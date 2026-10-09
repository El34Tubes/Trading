# Wolfy `agent_tasks.source` compatibility alias (2026-07-30)

## Trigger
A Mike ops run saw a fresh ad-hoc/read-only probe fail with:

```sql
select id, agent_name, source, task_type, status, title from agent_tasks ...
-- ERROR: column "source" does not exist
```

Canonical Wolfy task provenance is `source_table`, `source_id`, and `source_fingerprint`; `agent_tasks.source` is only a convenience alias for scratch probes/status queries.

## Safe repair pattern
Use a non-destructive nullable alias, not a rewrite of canonical task provenance:

```sql
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS source TEXT;
UPDATE agent_tasks
SET source = COALESCE(source, payload->>'source', source_table, 'agent_tasks')
WHERE source IS NULL;
```

Preserve it in:

- `/root/.hermes/wolfy/postgres_init.sql`
- canonical `/root/.hermes/scripts/mike_safe_autorepair.py`
- synced `/root/.hermes/wolfy/mike_safe_autorepair.py`
- synced profile wrappers under Mike/Clerky when autorepair manages them

If `wolfy_sync_agent_tasks_aliases()` exists, update the trigger to fill `NEW.source` from `NEW.payload->>'source'`, `NEW.source_table`, or `'agent_tasks'`, and include `source` in payload mirrors.

## Verification
Run real checks before reporting fixed:

```bash
psql -d wolfy -v ON_ERROR_STOP=1 -f /root/.hermes/wolfy/postgres_init.sql
psql -d wolfy -v ON_ERROR_STOP=1 -c "select count(*) filter (where source is null) as null_source_tasks, count(*) as total_tasks from agent_tasks;"
psql -d wolfy -v ON_ERROR_STOP=1 -c "select id,agent_name,source,task_type,status,title from agent_tasks order by id desc limit 3;"
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 -m py_compile /root/.hermes/scripts/mike_safe_autorepair.py /root/.hermes/wolfy/mike_safe_autorepair.py /root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py /root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py
```

Expected: exact query succeeds, `null_source_tasks=0`, first autorepair may sync wrapper copies, second autorepair is silent.

## Reporting nuance
This is schema-drift compatibility for read-only probes, not a trading-logic change and not a reason to mutate task ownership semantics.
