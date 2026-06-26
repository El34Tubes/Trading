# Wolfy autorepair non-mutating health checks — 2026-06-11

## Trigger

During a Wolfy optimization/blocker audit, the recurring Mike safe autorepair job was found to be creating repeated synthetic blocked tasks:

- `agent_name='Sentinel'`
- `task_type='review'`
- `title='Smoke blocked task'`

The source was `test_agent_coordination_smoke.py`, a DB-mutating pytest smoke test, being called every 30 minutes by `mike_safe_autorepair.py`.

## Durable lesson

Recurring watchdog/autorepair jobs must not run tests that intentionally mutate coordination tables unless the test cleans up perfectly and is explicitly designed for production recurrence. Use read-only/idempotent health checks for frequent jobs.

## Fix pattern

1. Remove DB-mutating smoke tests from recurring autorepair checks.
2. Keep safe recurring checks limited to:
   - Postgres guard/version requirement checks.
   - stale coordination cleanup.
   - embedding sync.
   - usage snapshot capture.
   - other idempotent/no-agent helpers.
3. If a coordination smoke test is needed, run it manually or in CI/test context, not every cron tick.
4. Sync patched wrapper copies across invocation layers when relevant:
   - `/root/.hermes/scripts/`
   - `/root/.hermes/wolfy/`
   - profile scripts such as `profiles/mike/scripts/` and `profiles/clerky/scripts/`.
5. Clear obvious synthetic rows only when their title/type/source proves they are test artifacts. Mark them completed with an explanatory note rather than deleting rows.
6. Reset stale diagnostic blockers to `queued` only if the description/run history proves no real research/action occurred.

## Verification pattern

After patching:

```bash
python3 -m py_compile /root/.hermes/scripts/mike_safe_autorepair.py /root/.hermes/wolfy/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py
```

Then inspect Postgres task status:

```sql
select status,count(*) from agent_tasks group by status order by count desc;
select count(*) as smoke_blocked_remaining
from agent_tasks
where title='Smoke blocked task' and status='blocked';
```

Expected healthy outcome:

- no active `Smoke blocked task` blockers.
- no recurring creation of synthetic Sentinel blocked review tasks.
- real queued work remains queued; real blockers are not blindly completed.

## Boundary

This does not authorize destructive database cleanup, broker/live-trading authority, or deleting legacy SQLite. Those still require explicit user approval.