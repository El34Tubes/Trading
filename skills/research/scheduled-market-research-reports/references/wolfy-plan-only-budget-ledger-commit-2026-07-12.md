# Wolfy plan-only budget ledger commit — 2026-07-12

## Trigger

Daily Wolfy optimizer ran while proactive budget gate was over cap:

```text
BUDGET=block token_cap_exceeded tokens_today=337507 cap=200000
```

The run therefore stayed PLAN-ONLY: no code/config/cron implementation, no schedule edits, no LLM-job re-enablement.

## Useful pattern

Even in PLAN-ONLY mode, it is useful to leave durable, machine-checkable state when the change is only the optimizer ledger/report trail:

1. Run `budget_gate.py --no-record` first for a non-mutating headroom check.
2. Run `config_guardian.py` or `config_guardian.py --skip-cli`, plus `hermes cron list`, to prove scheduler/guardian health.
3. Create/claim a Postgres `agent_tasks` row and start an `agent_runs` row for the plan-only run.
4. Insert `loop_metrics` rows for `jobs_skipped_by_budget`, `tokens_today`, `usage_headroom_pct`, `gateway_healthy`, `config_rollbacks`, `parallel_jobs_cap`, `max_turns`, and `human_approval_pending`.
5. Update `wolfy/optimization_todo.md` with concise facts and the next action.
6. Commit only that verified ledger file after checking staged contents.
7. If `agent_tasks` lacks explicit `commit_hash`, `verification_result`, or `verified_at` columns, store those values in `agent_tasks.payload` as JSONB.
8. Finish the run/task with a summary that says plan-only due to budget gate, not implementation completed.

## Verification commands used

```bash
python wolfy/guardian/budget_gate.py --no-record
python wolfy/guardian/config_guardian.py
hermes cron list
psql "$DSN" -Atc "select id,status,definition_of_done,summary from agent_tasks where id=<task_id>;"
git diff --cached --name-only
git show --stat --oneline -1
```

## Pitfalls

- Do not treat budget-gate block as permission to make Tier S implementation changes; state/KPI/ledger only.
- Do not commit broad dirty worktree state. Add only the verified ledger file and inspect staged paths before committing.
- Do not claim OWS-1 is complete merely because `budget_gate.py` exists; each LLM cron context path still needs budget no-op wiring (`skipped: budget` / `wakeAgent:false`) before token spend.
