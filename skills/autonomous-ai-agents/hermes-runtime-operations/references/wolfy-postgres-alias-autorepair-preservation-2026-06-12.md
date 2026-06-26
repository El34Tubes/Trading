# Wolfy Postgres alias preservation in autorepair layers (2026-06-12)

## Trigger

Mike's environment triage showed recurring Jonah/tool errors from ad-hoc probes using common Postgres display aliases. A prior compatibility layer existed in the live database, but recurring repair/schema files did not fully preserve the same aliases, so future init/autorepair runs could drift.

Aliases involved:

- `agent_runs.completed_at` mirrored from `ended_at`.
- `alpha_leads.company_name`, `alpha_leads.scanner_type`, `alpha_leads.score` mirrored from `raw_payload` / `lead_type` / `evidence_quality_score`.
- `scanner_results.company_name`, `scanner_results.scanner_type`, plus existing `scanner_run_id` and `status` aliases mirrored from `notes`, `run_id`, and `liquidity_pass`.

## Safe repair pattern

1. Keep the repair non-destructive:
   - `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` only.
   - Backfill nullable alias fields with `COALESCE(...)`.
   - Drop/recreate compatibility triggers instead of relying on stale `CREATE TRIGGER IF NOT EXISTS` definitions.
2. Preserve the same compatibility SQL in all durable layers:
   - `/root/.hermes/wolfy/mike_safe_autorepair.py`.
   - `/root/.hermes/scripts/mike_safe_autorepair.py`.
   - `/root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py`.
   - `/root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py`.
   - `/root/.hermes/wolfy/postgres_init.sql`.
   - Any local initializer that owns the table shape, e.g. `/root/.hermes/wolfy/alpha_search_pipeline.py` for Alpha Search tables.
3. Run the live SQL once and verify the second autorepair run is silent; empty stdout from the no-agent autorepair path is healthy.
4. Do not mutate credentials or remove tokens when investigating unrelated Copilot/GitHub auth warnings. Report those as setup issues unless the user explicitly asks for auth maintenance.

## Verification recipe

```bash
python3 -m py_compile \
  /root/.hermes/wolfy/mike_safe_autorepair.py \
  /root/.hermes/wolfy/alpha_search_pipeline.py

python3 /root/.hermes/wolfy/mike_safe_autorepair.py
python3 /root/.hermes/wolfy/mike_safe_autorepair.py  # should be silent
python3 /root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py
python3 /root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py

/root/.hermes/wolfy/check_postgres_requirements.py
psql -d wolfy -X -v ON_ERROR_STOP=1 -P pager=off \
  -c "select id, agent_name, status, task_id, started_at, completed_at from agent_runs order by id desc limit 3;" \
  -c "select id,ticker,company_name,status,scanner_type,score,created_at from alpha_leads order by id desc limit 3;" \
  -c "select id,ticker,company_name,status,scanner_type,score,created_at from scanner_results order by id desc limit 3;" \
  -c "select count(*) as stale_started_runs from agent_runs where status='started' and started_at < now() - interval '2 hours'; select count(*) as duplicate_claim_noise from agent_runs where error_message='duplicate-or-already-claimed' and started_at > now() - interval '6 hours'; select count(*) total, count(embedding) embedded from knowledge_chunks;"

cd /root/.hermes/wolfy
python3 -m pytest test_alpha_search_pipeline.py -q -o 'addopts='
```

Expected healthy markers from the session:

- autorepair wrappers: silent exit 0 after patch/sync.
- Postgres guard: PostgreSQL 16.x remains within requirements.
- stale started runs older than 2h: `0`.
- duplicate claim noise in last 6h: `0`.
- knowledge chunks: all embedded.
- Alpha Search regression: `5 passed`.

## Reporting note

Treat recent log tails as triage leads, not current truth. If the current cron list and smoke tests pass, report the stale historical failures as already addressed rather than inventing another fix.