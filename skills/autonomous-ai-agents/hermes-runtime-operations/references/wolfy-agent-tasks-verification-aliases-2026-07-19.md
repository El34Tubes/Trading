# Wolfy agent_tasks verification aliases (2026-07-19)

## Trigger
Recent optimizer/ops probes queried `agent_tasks.verification_result`, `commit_hash`, and `verified_at` as top-level columns. The live schema already had `definition_of_done`, `metadata`, and `payload`, but not all three verification aliases, causing ad-hoc optimizer warnings such as:

```text
ERROR: column "verification_result" does not exist
```

## Safe repair pattern
Use non-destructive compatibility aliases rather than changing canonical task write paths:

```sql
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS verification_result TEXT;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS commit_hash TEXT;
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;

UPDATE agent_tasks
SET verification_result = COALESCE(
  verification_result,
  metadata->>'verification_result',
  payload->>'verification_result',
  definition_of_done
)
WHERE verification_result IS NULL;

UPDATE agent_tasks
SET commit_hash = COALESCE(commit_hash, metadata->>'commit_hash', payload->>'commit_hash')
WHERE commit_hash IS NULL;
```

Preserve the aliases in both:

- `/root/.hermes/wolfy/postgres_init.sql`
- canonical `/root/.hermes/scripts/mike_safe_autorepair.py`, then run it to sync `/root/.hermes/wolfy/mike_safe_autorepair.py` plus Mike/Clerky profile copies.

Update `wolfy_sync_agent_tasks_aliases()` and `trg_agent_tasks_aliases_biu` so future inserts/updates mirror the fields into `payload` as JSON keys.

## Verification
Run:

```bash
psql -v ON_ERROR_STOP=1 -d wolfy -f /root/.hermes/wolfy/postgres_init.sql
python3 /root/.hermes/scripts/mike_safe_autorepair.py > /tmp/autorepair1.log
python3 /root/.hermes/scripts/mike_safe_autorepair.py > /tmp/autorepair2.log
python3 -m py_compile /root/.hermes/scripts/mike_safe_autorepair.py \
  /root/.hermes/wolfy/mike_safe_autorepair.py \
  /root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py \
  /root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py
psql -d wolfy -c "select column_name,data_type from information_schema.columns where table_name='agent_tasks' and column_name in ('verification_result','commit_hash','verified_at') order by column_name;"
psql -d wolfy -c "select id,status,title,definition_of_done,verification_result,commit_hash,verified_at from agent_tasks order by id desc limit 3;"
```

Expected:

- Postgres init exits 0.
- First autorepair may print sync lines; second run is silent.
- All copies compile.
- The three alias columns exist.
- Recent completed optimizer tasks have `verification_result` populated from `definition_of_done`.

## Reporting nuance
Treat the original missing-column warning as schema/probe drift, not a market-analysis or optimizer logic failure. If watchdogs and ledger counts are otherwise clean, report the alias preservation as the fix and do not claim broader runtime instability.