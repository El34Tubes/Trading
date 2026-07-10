# Wolfy Sentinel blocked-task duplicate no-op (2026-07-06)

## Trigger

A profile-scoped Mike ops run saw fresh `agent_runs.error_message='duplicate-or-already-claimed'` noise from the Sentinel review context while there were no stale started runs. The live row showed the Sentinel task was already `blocked` by stale-in-progress cleanup:

```sql
select t.id,t.status,t.title,t.source_fingerprint,t.updated_at,t.description
from agent_tasks t join agent_runs r on r.task_id=t.id
where r.id=<fresh_duplicate_run_id>;
```

The context helper's dedupe path treated `completed` tasks as no-op, but treated already-`blocked` tasks as a duplicate claim failure and opened a new blocked run every probe.

## Safe fix pattern

For context helpers that dedupe by `agent_tasks.source_fingerprint`, treat an already terminal task (`completed` **or** `blocked`) as a completed no-op run with `records_created=0` rather than writing a new `duplicate-or-already-claimed` blocker. Preserve the existing task blocker; do not unblock it automatically.

In `/root/.hermes/wolfy/sentinel_review_context.py`, the safe branch became:

```python
if ensured.status in {'completed', 'blocked'}:
    summary = f'Sentinel review task already {ensured.status}; no duplicate review work needed. task_id={ensured.id}'
    run_id = start_agent_run(..., status='completed', summary=summary)
    finish_agent_run(conn, run_id, status='completed', summary=summary, records_created=0)
    return run_id, None
```

Keep the non-terminal branch (`queued`, `in_progress`, etc.) as a true blocked duplicate/already-claimed event.

## Verification

Run both smoke-mode and real context checks:

```bash
python3 -m py_compile /root/.hermes/wolfy/sentinel_review_context.py /root/.hermes/scripts/wolfy_sentinel_review_context.py

before=$(psql -d wolfy -At -c "select count(*) from agent_runs where error_message='duplicate-or-already-claimed' and started_at > now() - interval '1 hour';")
WOLFY_CONTEXT_SMOKE=1 python3 /root/.hermes/scripts/wolfy_sentinel_review_context.py >/tmp/sentinel_smoke.out
after=$(psql -d wolfy -At -c "select count(*) from agent_runs where error_message='duplicate-or-already-claimed' and started_at > now() - interval '1 hour';")
printf 'duplicate_before=%s duplicate_after=%s\n' "$before" "$after"
```

If intentionally validating the non-smoke terminal-task path, expect one completed no-op run and no fresh duplicate noise:

```bash
before_dup=$(psql -d wolfy -At -c "select count(*) from agent_runs where error_message='duplicate-or-already-claimed' and started_at > now() - interval '1 hour';")
before_noop=$(psql -d wolfy -At -c "select count(*) from agent_runs where agent_name='Sentinel' and status='completed' and summary like 'Sentinel review task already blocked%' and started_at > now() - interval '1 hour';")
python3 /root/.hermes/scripts/wolfy_sentinel_review_context.py >/tmp/sentinel_real_context.out
after_dup=$(psql -d wolfy -At -c "select count(*) from agent_runs where error_message='duplicate-or-already-claimed' and started_at > now() - interval '1 hour';")
after_noop=$(psql -d wolfy -At -c "select count(*) from agent_runs where agent_name='Sentinel' and status='completed' and summary like 'Sentinel review task already blocked%' and started_at > now() - interval '1 hour';")
printf 'duplicate_before=%s duplicate_after=%s completed_noop_before=%s completed_noop_after=%s\n' "$before_dup" "$after_dup" "$before_noop" "$after_noop"
```

Then run autorepair twice and confirm fresh duplicate/stale-started counts remain zero.

## Pitfalls

- Do not mark the original blocked task completed unless a real review/blocker resolution occurred.
- Do not spend LLM review tokens on an already terminal task.
- Do not generalize this to active `in_progress` claims; those should still block or defer to stale-cleanup.