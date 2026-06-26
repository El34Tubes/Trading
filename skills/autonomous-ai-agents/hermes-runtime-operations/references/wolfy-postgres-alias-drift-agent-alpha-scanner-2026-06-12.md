# Wolfy Postgres alias drift: agent/alpha/scanner ad-hoc probes (2026-06-12)

## Trigger

Mike's scheduled environment triage saw recent Jonah/tool errors where LLM-authored probes queried common-but-missing Postgres columns, including:

- `agent_runs.completed_at` even though canonical column was `ended_at`.
- `alpha_leads.company_name`, `alpha_leads.scanner_type`, `alpha_leads.score`.
- `scanner_results.company_name`, `scanner_results.scanner_type`.

The live jobs were mostly healthy, so treat log tails as leads, not current truth. The safe response was a non-destructive compatibility layer, not a destructive schema rewrite or a claim that the jobs were broken.

## Safe repair pattern

1. Add nullable compatibility aliases with `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.
2. Backfill from canonical fields / JSON payloads:
   - `agent_runs.completed_at <- ended_at`.
   - `alpha_leads.scanner_type <- lead_type` first, then JSON payload fallbacks.
   - `alpha_leads.score <- raw_payload->>'score'` when numeric, else `evidence_quality_score` as a harmless display/probe fallback.
   - `scanner_results.company_name/scanner_type <- notes` JSON keys when present.
3. Add or replace triggers, dropping the old trigger first rather than relying on stale `CREATE TRIGGER IF NOT EXISTS` definitions.
4. Preserve the fix in every durable schema/repair layer:
   - `/root/.hermes/wolfy/mike_safe_autorepair.py`.
   - `/root/.hermes/scripts/mike_safe_autorepair.py` synced by autorepair.
   - Mike and Clerky profile copies of `mike_safe_autorepair.py`.
   - `/root/.hermes/wolfy/postgres_init.sql` for base schema drift prevention.
   - Pipeline-local table initializers such as `/root/.hermes/wolfy/alpha_search_pipeline.py` when they own `CREATE TABLE IF NOT EXISTS` statements.

## Verification commands

Run these after patching:

```bash
python3 -m py_compile \
  /root/.hermes/wolfy/mike_safe_autorepair.py \
  /root/.hermes/wolfy/alpha_search_pipeline.py

python3 /root/.hermes/wolfy/mike_safe_autorepair.py
python3 /root/.hermes/wolfy/mike_safe_autorepair.py   # second run should be silent

python3 /root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py
python3 /root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py

/root/.hermes/wolfy/check_postgres_requirements.py
psql -d wolfy -X -v ON_ERROR_STOP=1 -P pager=off \
  -c "select id, agent_name, status, task_id, started_at, completed_at from agent_runs order by id desc limit 3;" \
  -c "select id,ticker,company_name,status,scanner_type,score,created_at from alpha_leads order by id desc limit 3;" \
  -c "select id,ticker,company_name,status,scanner_type,score,created_at from scanner_results order by id desc limit 3;"
```

Also keep the existing health smoke:

```sql
select count(*) as stale_started_runs
from agent_runs
where status='started' and started_at < now() - interval '2 hours';

select count(*) as duplicate_claim_noise
from agent_runs
where error_message='duplicate-or-already-claimed'
  and started_at > now() - interval '6 hours';

select count(*) as synthetic_blocked_tasks
from agent_tasks
where status='blocked'
  and title='Smoke blocked task'
  and source_fingerprint like 'smoke-block-%';

select count(*) total, count(embedding) embedded from knowledge_chunks;
```

## Reporting note

If doctor still reports missing API keys/OAuth providers, report those as credential/setup gaps, not as broken dependencies. Do not harden transient tool/log errors into durable negative claims when the current cron status and smokes pass.
