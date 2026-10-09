# Wolfy Postgres compatibility aliases: `agent_tasks.claimed_by` and `alpha_leads.metadata` (2026-07-14)

## Trigger

Mike ops log tails showed ad-hoc/LLM-authored probes failing against live Wolfy Postgres because they expected common read-only aliases that were not present:

- `agent_tasks.claimed_by` in task/status probes.
- `alpha_leads.metadata` in Alpha/Jonah scanner-lead probes.

These were diagnostic/schema-compatibility drift issues, not market-logic failures.

## Safe repair pattern

Use non-destructive aliases and preserve them in every deterministic repair layer:

1. Add nullable/read-only compatibility columns in `wolfy/postgres_init.sql`:
   - `ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS claimed_by TEXT;`
   - `ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS metadata JSONB;`
2. Backfill from canonical fields:
   - `agent_tasks.claimed_by = COALESCE(assigned_agent, agent, agent_name)`
   - `alpha_leads.metadata = COALESCE(raw_payload, '{}'::jsonb)`
3. Update trigger helpers:
   - `wolfy_sync_agent_tasks_aliases()` should populate `claimed_by` and include it in `payload` JSON.
   - `wolfy_sync_alpha_leads_aliases()` should populate `metadata` from `raw_payload` and include `metadata` in the trigger update column list.
4. Preserve the same changes in canonical `/root/.hermes/scripts/mike_safe_autorepair.py`.
5. Run canonical autorepair once to sync:
   - `/root/.hermes/wolfy/mike_safe_autorepair.py`
   - `/root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py`
   - `/root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py`
6. Run autorepair a second time; it should be silent.

## Verification commands

```bash
python3 -m py_compile \
  /root/.hermes/scripts/mike_safe_autorepair.py \
  /root/.hermes/wolfy/mike_safe_autorepair.py \
  /root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py \
  /root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py

psql -d wolfy -v ON_ERROR_STOP=1 -f /root/.hermes/wolfy/postgres_init.sql
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py  # should be silent

psql -d wolfy -v ON_ERROR_STOP=1 -c "
select id,agent_name,task_type,title,status,claimed_by,claimed_at,started_at
from agent_tasks order by id desc limit 3;

select id,ticker,lead_type,status,score,source_fingerprint,created_at,updated_at,metadata
from alpha_leads order by id desc limit 3;

select count(*) filter (where claimed_by is not null) claimed_by_rows,
       count(*) total_tasks
from agent_tasks;

select count(*) filter (where metadata is not null) metadata_rows,
       count(*) total_alpha_leads
from alpha_leads;
"
```

Expected healthy shape from the original repair:

- `claimed_by_rows = total_tasks`.
- `metadata_rows = total_alpha_leads`.
- exact formerly failing probes selecting `claimed_by` and `metadata` exit 0.
- stale coordination cleanup, embedding sync, and usage-limit watchdogs remain silent.

## Reporting nuance

Treat historical log-tail failures as triage leads. If the live compatibility probes now pass and coordination counts are clean, report the alias preservation and verification; do not frame Jonah/Alpha Search as broken.