# Wolfy agent_tasks.blocker_reason compatibility alias (2026-07-07)

## Trigger

A Mike autonomous environment triage run surfaced a Postgres compatibility drift in an ops/optimizer probe:

```text
ERROR: column "blocker_reason" does not exist
```

The live canonical task table used `agent_tasks.error_message`, `summary`, and `description`, but ad-hoc/read-only probes expected a top-level `blocker_reason` column for blocked tasks.

## Safe repair pattern

Use the standard Wolfy non-destructive alias approach:

1. Add the alias column in both preservation layers:
   - `/root/.hermes/wolfy/postgres_init.sql`
   - canonical `/root/.hermes/scripts/mike_safe_autorepair.py`
2. Apply the live DB migration:
   ```sql
   ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS blocker_reason TEXT;
   UPDATE agent_tasks
   SET blocker_reason = COALESCE(blocker_reason, error_message, summary, description)
   WHERE status = 'blocked' AND blocker_reason IS NULL;
   ```
3. Update `wolfy_sync_agent_tasks_aliases()` so blocked tasks mirror both ways:
   - If `error_message` is missing, fill from `blocker_reason`, then summary/description.
   - If `blocker_reason` is missing, fill from `error_message`, then summary/description.
4. Include `blocker_reason` in the `agent_tasks.payload` JSON mirror.
   - Pitfall found in follow-up triage: many rows already have non-null `payload`, so `UPDATE ... WHERE payload IS NULL` is not enough.
   - Add a second merge update for existing payloads:
     ```sql
     UPDATE agent_tasks
     SET payload = jsonb_strip_nulls(payload || jsonb_build_object(
         'instruction', instruction,
         'error_message', error_message,
         'blocker_reason', blocker_reason,
         'source_table', source_table,
         'source_id', source_id
     ))
     WHERE payload IS NOT NULL
       AND (instruction IS NOT NULL OR error_message IS NOT NULL OR blocker_reason IS NOT NULL OR source_table IS NOT NULL OR source_id IS NOT NULL);
     ```
   - In `wolfy_sync_agent_tasks_aliases()`, keep the existing `IF NEW.payload IS NULL THEN jsonb_build_object(...)` branch, but add an `ELSE` branch that merges those alias keys into `NEW.payload` with `NEW.payload || jsonb_build_object(...)`.
5. Refresh the trigger with `DROP TRIGGER IF EXISTS ...; CREATE TRIGGER ...` and include `blocker_reason` in the `UPDATE OF ...` column list.
6. Run the initializer and autorepair:
   ```bash
   psql -d wolfy -f /root/.hermes/wolfy/postgres_init.sql
   /root/.hermes/scripts/mike_safe_autorepair.py
   /root/.hermes/scripts/mike_safe_autorepair.py
   ```
   The second autorepair run should be silent.

## Verification commands

```bash
psql -d wolfy -Atc "select 'blocked_tasks', count(*) from agent_tasks where status='blocked'; select 'blocked_with_alias', count(*) from agent_tasks where status='blocked' and coalesce(blocker_reason,'')<>''; select 'blocked_payload_mirror', count(*) from agent_tasks where status='blocked' and coalesce(payload->>'blocker_reason','')=coalesce(blocker_reason,'') and coalesce(blocker_reason,'')<>''; select 'stale_started_runs', count(*) from agent_runs where status='started' and started_at < now() - interval '2 hours'; select 'duplicate_claim_noise_recent', count(*) from agent_runs where error_message='duplicate-or-already-claimed' and started_at > now() - interval '24 hours';"

python3 -m py_compile /root/.hermes/scripts/mike_safe_autorepair.py /root/.hermes/wolfy/mike_safe_autorepair.py /root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py /root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py

grep -R "payload || jsonb_build_object" -n /root/.hermes/scripts/mike_safe_autorepair.py /root/.hermes/wolfy/mike_safe_autorepair.py /root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py /root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py /root/.hermes/wolfy/postgres_init.sql

python3 /root/.hermes/wolfy/visible_progress_ledger.py --limit 3
python3 /root/.hermes/wolfy/visible_progress_ledger.py --json >/tmp/visible_progress_ledger.json
cd /root/.hermes/wolfy && python3 -m pytest test_visible_progress_ledger.py -q
```

Expected healthy result from the session that introduced this note:

- `17|17` blocked tasks had `blocker_reason` populated.
- `stale_started_runs = 0`.
- `synthetic_blocked_tasks = 0`.
- `duplicate_claim_noise = 0`.
- Visible ledger Markdown and JSON both worked.
- Visible ledger tests passed: `2 passed`.
- Script-only smokes for embedding sync, stale cleanup, and usage snapshot were silent.

## Reporting nuance

If LLM-driven cron jobs show historical `HTTP 429 usage_limit_reached` in `Last run` but are currently active and the no-agent usage watchdog is silent, report that as prior quota pressure under watchdog control, not as a newly broken runtime path.