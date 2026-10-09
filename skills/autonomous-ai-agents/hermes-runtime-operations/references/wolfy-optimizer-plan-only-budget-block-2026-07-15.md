# Wolfy optimizer plan-only budget block — 2026-07-15

Use this as the pattern for a scheduled Wolfy optimizer run when the deterministic budget gate blocks implementation.

## Trigger

- `wolfy/guardian/budget_gate.py` exits non-zero with `BUDGET=block ...` (example: `token_cap_exceeded tokens_today=323156 cap=200000`).
- The optimizer instructions say to enter PLAN-ONLY mode: review/state/KPI updates only; no code/config/cron implementation.

## Correct sequence

1. Confirm scheduler/guardian state without making orchestration changes.
   - `hermes cron list` must succeed and the optimizer job must remain active.
   - Use `python3 wolfy/guardian/config_guardian.py --skip-cli` for a cheap guardian/config health check.
   - Do **not** use `--health-only`; current `config_guardian.py` does not support that flag.
2. Persist the plan-only run in Postgres.
   - `wolfy_agent_cli.py task-ensure` with a stable source fingerprint for the date/reason.
   - `task-claim`, then `run-start`.
   - Set `agent_tasks.definition_of_done` to a plan-only DoD: budget block captured, guardian checked, no code/config/cron changes, task/run/metrics persisted.
3. Record KPIs in `loop_metrics`, at minimum:
   - `tokens_today`
   - `usage_headroom_pct`
   - `jobs_skipped_by_budget=1`
   - `gateway_healthy`
   - `config_rollbacks`
   - `max_turns`
   - `parallel_jobs_cap`
   - `human_approval_pending`
   - `iteration_success_rate`
   - `regressions_introduced=0`
4. Update `/root/.hermes/wolfy/optimization_todo.md` with a concise entry capturing budget output, guardian result, task/run IDs, and next action.
5. Complete the plan-only task/run and commit only the durable ledger note, not unrelated dirty files.
   - Commit shape used: `wolfy(opt): record budget-blocked plan-only run — DoD met (task <id>)`.
   - Store the local commit hash in the task payload/verification fields.

## Pitfalls

- Budget-blocked means **no Tier S implementation**, even if the next backlog item is obvious.
- Do not treat `config_guardian.py --health-only` failure as guardian failure; it is an unsupported CLI option. Re-run with `--skip-cli` (or the pinned wrapper when profile/home pinning matters).
- Do not commit broad pre-existing dirty worktree changes; only stage the ledger/reference file(s) created by the plan-only run.
- A final report should be concise: CHANGED, VERIFIED, KPI/STATE, BLOCKED/HUMAN ASK, NEXT ACTION.
