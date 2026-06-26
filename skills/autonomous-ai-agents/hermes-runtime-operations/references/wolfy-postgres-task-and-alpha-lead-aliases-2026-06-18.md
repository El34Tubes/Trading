# Wolfy Postgres task and alpha-lead alias drift (2026-06-18)

## Trigger

Mike's autonomous triage saw repeated Jonah/tool failures from ad-hoc Postgres probes selecting columns that were not guaranteed in the canonical schema:

- `agent_tasks.source_table`
- `agent_tasks.source_id`
- `alpha_leads.scanner_run_id`
- `alpha_search_leads.scanner_run_id`

These were read-only/probe compatibility problems, not evidence that the live Postgres-primary pipeline was broken.

## Safe repair pattern

Use non-destructive compatibility aliases and preserve them in both schema initialization and autorepair:

1. Add nullable alias columns:
   - `ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS source_table TEXT;`
   - `ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS source_id TEXT;`
   - `ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS scanner_run_id BIGINT;`
2. Backfill:
   - `agent_tasks.source_table = COALESCE(source_table, payload->>'source_table', 'agent_tasks')`
   - `agent_tasks.source_id = COALESCE(source_id, payload->>'source_id', source_fingerprint, id::text)`
   - `alpha_leads.scanner_run_id` from numeric `raw_payload->>'scanner_run_id'`, `raw_payload->>'scanner_run'`, or `raw_payload->>'run_id'`.
3. Update the alias triggers so future inserts/updates populate those aliases.
4. When exposing the new column from `alpha_search_leads`, use `DROP VIEW IF EXISTS alpha_search_leads; CREATE VIEW ...` rather than `CREATE OR REPLACE VIEW` if the view column list changes. Postgres can reject column-list changes with `cannot change name of view column` / `cannot drop columns from view`.
5. Preserve the same SQL in:
   - `/root/.hermes/wolfy/postgres_init.sql`
   - `/root/.hermes/scripts/mike_safe_autorepair.py`
6. Run the global autorepair wrapper so it syncs Wolfy/profile copies:
   - `/root/.hermes/scripts/mike_safe_autorepair.py`
   - run it a second time; the second run should be silent except for genuinely new issues.

## Verification commands

```bash
psql -d wolfy -v ON_ERROR_STOP=1 -q -f /root/.hermes/wolfy/postgres_init.sql
/root/.hermes/scripts/mike_safe_autorepair.py
/root/.hermes/scripts/mike_safe_autorepair.py

psql -d wolfy -v ON_ERROR_STOP=1 \
  -c "select id,title,task_type,status,source_table,source_id,payload from agent_tasks order by id desc limit 1;" \
  -c "select id,ticker,lead_type,title,status,scanner_run_id,source_fingerprint,created_at,updated_at,filing_context,insider_context,next_research_question,raw_payload from alpha_leads order by id desc limit 1;" \
  -c "select scanner_run_id from alpha_search_leads order by id desc limit 1;"

psql -d wolfy \
  -c "select count(*) filter (where status='started' and started_at < now()-interval '2 hours') stale_started_runs from agent_runs;" \
  -c "select count(*) filter (where title ilike '%Smoke blocked task%' and status='blocked') synthetic_blocked_tasks from agent_tasks;" \
  -c "select count(*) duplicate_claim_noise from agent_runs where error_message='duplicate-or-already-claimed' and started_at > now()-interval '6 hours';" \
  -c "select count(*) total, count(embedding) embedded, count(*)-count(embedding) missing from knowledge_chunks;"
```

## Expected healthy state from the session

- `agent_tasks` exposes `source_table/source_id` and probe queries work.
- `alpha_leads` exposes `scanner_run_id` backfilled from raw payload.
- `alpha_search_leads` exposes `scanner_run_id`.
- No stale started runs, no synthetic blocked smoke tasks, no duplicate-claim noise.
- Knowledge chunks fully embedded.
