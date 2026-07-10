# Wolfy alpha_leads risk_flags compatibility alias (2026-07-02)

## Trigger
Recent Jonah ad-hoc verification probes repeatedly queried `alpha_leads.risk_flags` after scanner-alpha research runs. The live Postgres `alpha_leads` table exposed `suspicious_flags` and `raw_payload->'risk_flags'`, but had no top-level `risk_flags` column, producing `psycopg2.errors.UndefinedColumn: column "risk_flags" does not exist` warnings.

## Safe repair pattern
Use the standard non-destructive Postgres alias-drift fix:

```sql
ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS risk_flags JSONB NOT NULL DEFAULT '[]';
UPDATE alpha_leads
SET risk_flags = COALESCE(
  NULLIF(risk_flags, '[]'::jsonb),
  raw_payload->'risk_flags',
  suspicious_flags,
  raw_payload->'suspicious_flags',
  '[]'::jsonb
)
WHERE risk_flags IS NULL OR risk_flags = '[]'::jsonb;
```

Then refresh the alpha-lead alias trigger so new/updated rows preserve the alias:

```sql
IF NEW.risk_flags IS NULL OR NEW.risk_flags = '[]'::jsonb THEN
  NEW.risk_flags := COALESCE(
    NEW.raw_payload->'risk_flags',
    NEW.suspicious_flags,
    NEW.raw_payload->'suspicious_flags',
    '[]'::jsonb
  );
END IF;
```

Include `risk_flags` in the `alpha_search_leads` compatibility view when probes use that retired/compat relation.

## Files to preserve
Patch every durable preservation layer, not just the live DB:

- `/root/.hermes/wolfy/postgres_init.sql`
- `/root/.hermes/scripts/mike_safe_autorepair.py`
- `/root/.hermes/wolfy/mike_safe_autorepair.py`
- profile copies synced by autorepair, especially:
  - `/root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py`
  - `/root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py`
- pipeline-local initializer if it creates/repairs `alpha_leads`, e.g. `/root/.hermes/wolfy/alpha_search_pipeline.py`

## Verification
Run real checks before reporting fixed:

```bash
python3 -m py_compile \
  /root/.hermes/scripts/mike_safe_autorepair.py \
  /root/.hermes/wolfy/mike_safe_autorepair.py \
  /root/.hermes/wolfy/alpha_search_pipeline.py

/root/.hermes/scripts/mike_safe_autorepair.py
/root/.hermes/scripts/mike_safe_autorepair.py  # second run should be silent

psql -d wolfy -Atc "
select count(*) from information_schema.columns
 where table_schema='public' and table_name='alpha_leads' and column_name='risk_flags';
select count(*) from information_schema.columns
 where table_schema='public' and table_name='alpha_search_leads' and column_name='risk_flags';
select count(*) from alpha_leads where risk_flags is null;
select id,ticker,risk_flags from alpha_leads order by id desc limit 5;
"
```

Also rerun the core quiet smokes used by Mike ops:

```bash
/root/.hermes/wolfy/check_postgres_requirements.py
/root/.hermes/scripts/wolfy_embed_knowledge_chunks.py
/root/.hermes/scripts/wolfy_cleanup_stale_agent_coordination.py
/root/.hermes/scripts/wolfy_capture_usage_snapshot.py
psql -d wolfy -Atc "
select 'stale_started_runs', count(*) from agent_runs where status='started' and started_at < now() - interval '2 hours';
select 'synthetic_blocked_tasks', count(*) from agent_tasks where status='blocked' and (title ilike '%smoke%' or description ilike '%smoke%');
select 'duplicate_claim_noise_recent', count(*) from agent_runs where error_message='duplicate-or-already-claimed' and started_at > now() - interval '12 hours';
"
```

## Reporting
Report this as a compatibility alias repair, not a market-analysis change. If the smokes are silent and coordination counts are zero, there is no need to alert beyond the concise fixed/verified summary for the current ops run.