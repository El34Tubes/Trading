# Wolfy tiered-backfill wrapper sync + `agent_tasks.started_at` alias (2026-07-09)

## Trigger

Mike ops pre-run context showed recent warnings:

- `No such file or directory: /root/.hermes/wolfy/wolfy_tiered_backfill_bounded.py` while the live cron wrapper existed only at `/root/.hermes/scripts/wolfy_tiered_backfill_bounded.py`.
- Ad-hoc/ops SQL probes expected `agent_tasks.started_at`, but canonical `agent_tasks` had `claimed_at`, `created_at`, `updated_at`, and `completed_at` only.

## Safe repair pattern

1. Treat missing legacy/profile wrapper paths as compatibility drift, not as a broken backfill implementation.
2. Patch canonical `/root/.hermes/scripts/mike_safe_autorepair.py` first so the fix survives the next self-sync.
3. Add `wolfy_tiered_backfill_bounded.py` to:
   - `MIKE_SCRIPTS`
   - `CLERKY_SCRIPTS`
   - `WOLFY_SCRIPTS_FROM_GLOBAL`
4. Run canonical autorepair twice:
   ```bash
   python3 /root/.hermes/scripts/mike_safe_autorepair.py
   python3 /root/.hermes/scripts/mike_safe_autorepair.py
   ```
   First run should sync wrapper/autorepair copies; second run should be silent.
5. Verify wrapper compile/executable state across all invocation layers:
   ```bash
   python3 -m py_compile \
     /root/.hermes/scripts/mike_safe_autorepair.py \
     /root/.hermes/wolfy/mike_safe_autorepair.py \
     /root/.hermes/scripts/wolfy_tiered_backfill_bounded.py \
     /root/.hermes/wolfy/wolfy_tiered_backfill_bounded.py \
     /root/.hermes/profiles/mike/scripts/wolfy_tiered_backfill_bounded.py \
     /root/.hermes/profiles/clerky/scripts/wolfy_tiered_backfill_bounded.py \
     /root/.hermes/wolfy/backfill_tiered_remaining.py
   ```

## `agent_tasks.started_at` compatibility alias

When durable read-only probes expect `agent_tasks.started_at`, add it non-destructively rather than rewriting canonical task-claim logic:

```sql
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
UPDATE agent_tasks
SET started_at = COALESCE(started_at, claimed_at, created_at)
WHERE started_at IS NULL;
```

Preserve it in `mike_safe_autorepair.py`:

- add the column in `ensure_postgres_compatibility_aliases()`
- backfill it from `claimed_at`/`created_at`
- include it in the `payload` JSONB mirror
- update `wolfy_sync_agent_tasks_aliases()` so new rows set `NEW.started_at := COALESCE(NEW.claimed_at, NEW.created_at)`
- include `claimed_at, started_at` in the trigger `UPDATE OF` column list

Verification:

```bash
psql -d wolfy -c "select id,title,status,agent_name,updated_at,created_at,started_at from agent_tasks order by id desc limit 1;"
psql -d wolfy -c "select count(*) as null_started_at from agent_tasks where started_at is null;"
```

Expected after repair: query works and `null_started_at = 0` unless intentionally sparse legacy rows exist.

## Reporting nuance

If cron `Next run` timestamps are just-due/stale while a Mike LLM cron session is active and `/root/.hermes/cron/.tick.lock` was just touched, treat that as an active-tick artifact. Verify direct script smokes and wrapper presence; do not declare scheduler failure until stale timestamps persist after the active run exits.
