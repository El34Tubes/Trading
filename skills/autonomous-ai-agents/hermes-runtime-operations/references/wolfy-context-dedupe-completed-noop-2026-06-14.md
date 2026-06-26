# Wolfy context dedupe: completed tasks are no-op, not blocked noise

Session date: 2026-06-14

## Problem

Mike's operations triage saw recent `agent_runs.error_message='duplicate-or-already-claimed'` noise after Yang/Sentinel context helpers deduped work by `agent_tasks.source_fingerprint`.

One live example was a Yang post-Sentinel run where the deduped `agent_tasks` row was already `completed`, but `yang_technical_context.py` wrote a new `blocked` run anyway:

```sql
select id, agent_name, role, task_id, status, error_message, summary
from agent_runs
where error_message='duplicate-or-already-claimed'
order by started_at desc
limit 1;
-- id=82718, agent_name=Yang, role=technical_entry_exit,
-- task_id=2588, status=blocked,
-- summary='Duplicate/already claimed Yang task; status=completed.'
```

This made ops smoke checks look unhealthy even though no work was actually blocked; the prior task had already finished.

## Durable fix pattern

For context helpers that use `ensure_agent_task(... source_fingerprint=...)` followed by `claim_next_task(...)`:

1. If `claim_next_task()` returns `None`, inspect the deduped task status returned by `ensure_agent_task()`.
2. If `ensured.status == 'completed'`, create/finish the run as `completed` with `records_created=0`, not `blocked`.
3. Reserve `blocked` + `error_message='duplicate-or-already-claimed'` for genuinely active/in-progress claims or truly blocked deduped tasks.
4. Include a clear summary such as:
   - `Yang task already completed; no duplicate technical-analysis work needed. task_id=<id>`
   - `Sentinel review task already completed; no duplicate review work needed. task_id=<id>`

Applied to:

- `/root/.hermes/wolfy/yang_technical_context.py`
- `/root/.hermes/wolfy/sentinel_review_context.py`

## Smoke-mode rule

Operations probes should not claim real downstream work. Add/support:

```bash
WOLFY_CONTEXT_SMOKE=1 python3 /root/.hermes/wolfy/yang_technical_context.py
WOLFY_CONTEXT_SMOKE=1 python3 /root/.hermes/wolfy/sentinel_review_context.py
```

Expected signal:

```text
Postgres agent run: SMOKE_MODE=true no agent_runs row opened and no agent_task claimed
```

If a manual smoke accidentally claims a task:

```sql
-- Identify the smoke run and task.
select id, task_id, status, summary
from agent_runs
where id=<smoke_run_id>;

-- Return the claimed task to queued if no downstream work was performed.
update agent_tasks
set status='queued', claim_token=null, claimed_at=null, updated_at=now()
where id=<task_id> and status='in_progress';

-- Mark the smoke run completed/no-op.
update agent_runs
set status='completed', ended_at=now(), completed_at=now(),
    records_created=0,
    summary='Mike operations context smoke only; no downstream work performed and task returned to queued.',
    error_message=null
where id=<smoke_run_id>;
```

## Verification

Run the non-destructive checks:

```bash
/root/.hermes/wolfy/check_postgres_requirements.py
psql -d wolfy -v ON_ERROR_STOP=1 -c "
SELECT count(*) AS stale_started_runs
FROM agent_runs
WHERE status='started' AND started_at < now() - interval '2 hours';

SELECT count(*) AS synthetic_blocked_tasks
FROM agent_tasks
WHERE status='blocked'
  AND title='Smoke blocked task'
  AND source_fingerprint LIKE 'smoke-block-%';

SELECT count(*) AS duplicate_claim_noise
FROM agent_runs
WHERE status='blocked'
  AND error_message='duplicate-or-already-claimed'
  AND started_at > now() - interval '24 hours';
"
```

Healthy values from the fix session:

```text
stale_started_runs = 0
synthetic_blocked_tasks = 0
duplicate_claim_noise = 0
```

Also verify context smoke mode:

```bash
WOLFY_CONTEXT_SMOKE=1 python3 /root/.hermes/wolfy/yang_technical_context.py >/tmp/yang.out
WOLFY_CONTEXT_SMOKE=1 python3 /root/.hermes/wolfy/sentinel_review_context.py >/tmp/sentinel.out
grep 'SMOKE_MODE=true' /tmp/yang.out /tmp/sentinel.out
```

## Triage nuance

When updating Mike triage queries, count only active blocked duplicate noise:

```sql
SELECT count(*) AS duplicate_claim_noise
FROM agent_runs
WHERE status='blocked'
  AND error_message='duplicate-or-already-claimed'
  AND started_at > now() - interval '24 hours';
```

Do not count completed no-op duplicate detections as operational failures.
