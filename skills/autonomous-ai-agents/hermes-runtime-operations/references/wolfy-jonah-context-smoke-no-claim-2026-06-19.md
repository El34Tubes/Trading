# Wolfy Jonah context smoke mode must not claim work (2026-06-19)

## Trigger
Operations triage/smoke tests need to verify Jonah context generators without mutating the Postgres coordination ledger.

## Failure mode
Running the Jonah context wrapper with `WOLFY_CONTEXT_SMOKE=1` still claimed a queued `agent_tasks` row and opened an `agent_runs.status='started'` row. This polluted the live queue and could make operations smoke tests look like real Jonah work.

Observed cleanup pattern:

```sql
UPDATE agent_runs
SET status='completed', ended_at=now(), records_created=0,
    summary='Closed accidental operations smoke claim; WOLFY_CONTEXT_SMOKE now avoids opening Jonah runs.',
    error_message=NULL
WHERE id=<run_id> AND status='started' AND agent_name='Jonah';

UPDATE agent_tasks
SET status='queued', claim_token=NULL, claimed_at=NULL, updated_at=now()
WHERE id=<task_id> AND status='in_progress' AND claim_token='<claim_token>';
```

## Durable fix pattern
Context helpers that are routinely used by Mike/ops smoke tests should check smoke mode **before** task claiming or `agent_run` creation:

```python
import os

if os.environ.get('WOLFY_CONTEXT_SMOKE') == '1':
    print('Postgres agent task claim: SMOKE=true; no task claimed and no agent_run opened.')
    print('Instruction: smoke verification only; live cron may claim queued tasks normally.')
    return
```

Place this after read-only context/count printing but before `claim_next_task()`, `start_agent_run()`, or task status updates.

## Verification
Use before/after counts to prove the smoke is non-mutating:

```bash
before=$(psql -d wolfy -X -At -c "select count(*) from agent_runs where agent_name='Jonah' and status='started'; select count(*) from agent_tasks where status='in_progress';")
WOLFY_CONTEXT_SMOKE=1 python3 /root/.hermes/scripts/wolfy_hourly_knowledge_context.py >/tmp/wolfy_hourly_context_smoke.out
after=$(psql -d wolfy -X -At -c "select count(*) from agent_runs where agent_name='Jonah' and status='started'; select count(*) from agent_tasks where status='in_progress';")
printf 'before:\n%s\nafter:\n%s\n' "$before" "$after"
grep -F "SMOKE=true; no task claimed" /tmp/wolfy_hourly_context_smoke.out
```

Expected: before and after counts match, and the smoke marker is present.

## Reporting nuance
If this smoke path is fixed and duplicate-claim noise is zero in the recent window, report it as a verification/cleanup result, not as a market-analysis issue. Leave queued Jonah research tasks queued for the live Jonah cron to claim normally.