# Wolfy optimizer plan-only budget gate — 2026-08-11

Use this as a compact reference for future Wolfy daily optimizer runs that start over the deterministic budget cap.

## Trigger

At Phase 0, the budget gate returned:

```text
BUDGET=block token_cap_exceeded tokens_today=226094 cap=200000
```

This is a hard PLAN-ONLY stop. Do not implement code/config/cron changes after this result, even if the next backlog item is Tier S.

## Safe plan-only sequence that worked

1. Run the cheap deterministic checks only:
   - `python3 wolfy/guardian/budget_gate.py --no-record`
   - `python3 wolfy/guardian/config_guardian.py --skip-cli`
   - `hermes cron list`
   - visible progress ledger / open task queries
2. Create or reuse a dated optimizer plan-only `agent_tasks` row with a stable fingerprint such as `wolfy-optimizer-plan-only-budget-block-YYYY-MM-DD`.
3. Claim only that plan-only task; do not claim implementation tasks while budget-blocked.
4. Associate the current optimizer `agent_runs.status='started'` row with the plan-only task when present.
5. Insert `loop_metrics` rows for the budget block and current state, including at minimum:
   - `tokens_today`
   - `usage_headroom_pct`
   - `jobs_skipped_by_budget=1`
   - `gateway_healthy`
   - `config_rollbacks`
   - `max_turns`
   - `parallel_jobs_cap`
   - `human_approval_pending`
   - `regressions_introduced=0`
6. Update `wolfy/optimization_todo.md` with a concise dated entry.
7. Commit only the intended ledger/doc hunk if a repo change was made; leave dirty unrelated profile/curator/autorepair files untouched.
8. Store verification metadata and commit hash on the `agent_tasks` row, then complete the task and finish the run.

## Verification commands/output shape

Before completing the task/run, verify:

```text
select id,status,definition_of_done is not null, verification_result is not null
from agent_tasks where id=<task_id>;

select count(*)
from loop_metrics
where run_id=<run_id> and captured_at > now() - interval '10 minutes';

hermes cron list   # exit 0
```

After completion, verify:

```text
final_task (<task_id>, 'completed', '<commit_hash>', True, True)
final_run (<run_id>, 'completed', True, 0, 'Plan-only due to budget gate ...')
```

## Pitfall discovered

When updating JSONB metadata with psycopg, avoid ambiguous `jsonb_build_object('commit_hash', %s)` parameters if PostgreSQL cannot infer the type. Use a JSON string cast instead:

```python
cur.execute("""
update agent_tasks
set commit_hash=%s,
    metadata=coalesce(metadata,'{}'::jsonb) || %s::jsonb,
    payload=coalesce(payload,'{}'::jsonb) || %s::jsonb,
    updated_at=now()
where id=%s
""", (commit, json.dumps({'commit_hash': commit}), json.dumps({'commit_hash': commit}), task_id))
```

If the commit succeeds but the follow-up DB write fails, do not leave the run half-finished: rerun only the failed DB write, re-query task/run/metric rows, then complete the task and finish the run.

## Report shape

Keep the final cron report short:

- `CHANGED`: plan-only state persisted, no implementation/config/cron changes.
- `VERIFIED`: budget blocked, guardian ok, cron list ok, metrics/task/run complete, commit hash.
- `KPI/STATE`: headroom, skipped-by-budget, guardian/concurrency state.
- `BLOCKED/HUMAN ASK`: none unless Tier B was actually encountered.
- `NEXT ACTION`: one concrete backlog item for when budget recovers.