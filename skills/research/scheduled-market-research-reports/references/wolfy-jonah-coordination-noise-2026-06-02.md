# Wolfy/Jonah coordination noise fix — 2026-06-02

## Symptom

Mike's autonomous environment triage saw Postgres `agent_runs` accumulating repeated Jonah rows like:

- `status='blocked'`
- `error_message='duplicate-or-already-claimed'`
- summary similar to `No claim available; task status=blocked`

The rows appeared every Jonah cron tick even though the underlying task/source had already been claimed, completed, or blocked.

## Root cause

`/root/.hermes/wolfy/hourly_knowledge_context.py` selected both queued and stale local SQLite `in_progress` work:

```sql
WHERE status IN ('queued','in_progress')
```

It then built the same Postgres `source_fingerprint` and attempted to claim the already blocked/deduped Postgres task again, producing a fresh blocked `agent_runs` row each time.

## Safe fix pattern

Context generators should claim only fresh queued work. Stale `in_progress` cleanup belongs to the coordination watchdog.

Patch pattern:

```python
# Only queue fresh work here. Re-selecting stale SQLite ``in_progress`` rows
# creates deduped/blocked Postgres rows every cron tick after the original
# claim has already completed or blocked. Stale in-progress cleanup is owned by
# the coordination watchdog, not by the context generator.
task = con.execute(
    "SELECT * FROM training_tasks WHERE status = 'queued' "
    "ORDER BY priority ASC, COALESCE(last_attempt_at,'') ASC, id ASC LIMIT 1"
).fetchone()
source = con.execute(
    "SELECT * FROM knowledge_sources WHERE status = 'queued' "
    "ORDER BY priority ASC, id ASC LIMIT 1"
).fetchone()
```

## Verification commands used

```bash
python3 -m pytest \
  /root/.hermes/wolfy/test_eod_governance.py \
  /root/.hermes/wolfy/test_agent_coordination_smoke.py \
  /root/.hermes/wolfy/tests/test_embed_knowledge_chunks.py \
  /root/.hermes/wolfy/test_eod_price_features.py \
  /root/.hermes/wolfy/test_eod_backtest.py -q

python3 /root/.hermes/scripts/wolfy_cleanup_stale_agent_coordination.py >/tmp/stale.out 2>/tmp/stale.err
python3 /root/.hermes/scripts/mike_safe_autorepair.py >/tmp/repair.out 2>/tmp/repair.err

psql -d wolfy -c "select count(*) as blocked_duplicates_since_fix_window from agent_runs where status='blocked' and error_message='duplicate-or-already-claimed' and started_at > '<fix timestamp>';"
```

Expected: pytest passes, watchdog/autorepair are silent with rc=0, and duplicate blocked count remains zero after the fix window.

## Related test hardening

If a smoke test checks current cron prompts for EOD constitution text, do not make it fail on retired one-off historical job IDs. Validate constitution fields for jobs that still exist in `jobs.json`; durable cron config evolves.
