# Wolfy Postgres agent ledger compatibility aliases — 2026-06-18

## Trigger

Jonah/Wolfy ad-hoc diagnostic snippets began querying convenience columns that were not part of the canonical Postgres coordination schema:

- `agent_tasks.payload`
- `agent_runs.result_summary`

The live tables already had canonical fields (`agent_tasks.*`, `agent_tasks.summary`, `agent_runs.summary`), but LLM-authored probes failed before getting to the real research/debugging task.

## Safe fix pattern

Use non-destructive compatibility aliases, then preserve them in both schema init and the deterministic autorepair loop.

```sql
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS payload JSONB;
UPDATE agent_tasks
SET payload = jsonb_strip_nulls(jsonb_build_object(
    'id', id,
    'agent_name', agent_name,
    'task_type', task_type,
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

ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS result_summary TEXT;
UPDATE agent_runs
SET result_summary = summary
WHERE result_summary IS NULL AND summary IS NOT NULL;
```

Refresh triggers so future inserts/updates keep aliases populated:

- `wolfy_sync_agent_tasks_aliases()` should fill `summary`, `error_message`, and `payload` when absent.
- `wolfy_sync_agent_runs_aliases()` should mirror `summary` and `result_summary` in both directions, and continue mirroring `ended_at` / `completed_at`.

## Preservation points

Patch both:

- `/root/.hermes/wolfy/postgres_init.sql`
- `/root/.hermes/scripts/mike_safe_autorepair.py`

Then run the global autorepair script so it syncs copies to:

- `/root/.hermes/wolfy/mike_safe_autorepair.py`
- `/root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py`
- `/root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py`

## Verification commands

```bash
python3 -m py_compile \
  /root/.hermes/scripts/mike_safe_autorepair.py \
  /root/.hermes/wolfy/mike_safe_autorepair.py \
  /root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py \
  /root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py

/root/.hermes/scripts/mike_safe_autorepair.py
/root/.hermes/scripts/mike_safe_autorepair.py   # second run should be silent

psql -d wolfy -c "select column_name,data_type from information_schema.columns where table_name='agent_tasks' and column_name in ('payload','summary','error_message') order by column_name;"
psql -d wolfy -c "select column_name,data_type from information_schema.columns where table_name='agent_runs' and column_name in ('completed_at','result_summary','summary') order by column_name;"
psql -d wolfy -c "select count(*) filter (where payload is not null) payload_rows, count(*) total from agent_tasks;"
psql -d wolfy -c "select count(*) filter (where result_summary is not null) result_summary_rows, count(*) total from agent_runs;"

# exact failing-style probes
psql -d wolfy -c "select id,title,task_type,status,payload,source_fingerprint from agent_tasks order by id desc limit 3;"
psql -d wolfy -c "select id,status,records_created,result_summary from agent_runs order by id desc limit 3;"
```

Also run normal ops checks afterward:

```bash
/root/.hermes/wolfy/check_postgres_requirements.py
psql -d wolfy -c "select count(*) as stale_started_runs from agent_runs where status='started' and started_at < now() - interval '2 hours';"
psql -d wolfy -c "select count(*) as synthetic_blocked_tasks from agent_tasks where status='blocked' and title ilike '%Smoke blocked task%';"
psql -d wolfy -c "select count(*) as duplicate_claim_noise from agent_runs where error_message='duplicate-or-already-claimed' and started_at > now() - interval '24 hours';"
```

## Reporting rule

Report this as a schema-compatibility fix, not a market-analysis change. It is additive and operational: no trading logic, no destructive DB changes, no credential workaround.
