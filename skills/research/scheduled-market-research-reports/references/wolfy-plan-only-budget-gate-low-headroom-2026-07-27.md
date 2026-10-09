# Wolfy plan-only budget-gate low-headroom run — 2026-07-27

## Context
The daily Wolfy optimizer ran as a scheduled cron job with the self-optimizing control-plane prompt. The proactive budget gate existed and returned low headroom, so the run had to be plan-only: orient/review/state/KPI updates, no code/config/cron implementation.

## Verified outputs
- `python3 wolfy/guardian/budget_gate.py --no-record` returned `BUDGET=block low_headroom_pct=8.01 threshold=15.00` with exit 1.
- `python3 wolfy/guardian/config_guardian.py --skip-cli` returned `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;no_probation`.
- `hermes cron list` succeeded and showed optimizer job `92f31b95fccc` still active for the next scheduled run.
- Postgres task `3608` and run `357210` were completed as plan-only progress.

## Durable workflow pattern
When the budget gate blocks on `low_headroom_pct` and its output does not include `tokens_today`, do not invent or omit the token KPI. Query it deterministically from Postgres:

```sql
SELECT COALESCE(SUM(COALESCE(input_tokens,0)+COALESCE(output_tokens,0)),0)
FROM agent_runs
WHERE started_at >= date_trunc('day', now() AT TIME ZONE 'America/New_York') AT TIME ZONE 'America/New_York';
```

Then insert both `tokens_today` and `usage_headroom_pct` into `loop_metrics` for the current optimizer run.

## CLI/schema notes
- `wolfy_agent_cli.py` does not have `task-create`; use `task-ensure` to create/dedupe tasks, then `task-claim`, `run-start`, `task-complete`, and `run-finish`.
- Current `agent_runs` has no `verification_result`; store verification in `agent_tasks.definition_of_done`, task summary/metadata, and run summary/records.
- `loop_metrics` has compatibility aliases (`metric_name`, `value_numeric`), but canonical inserts should still provide `metric_key` and `metric_value`.

## Reporting shape
For budget-blocked optimizer runs, the final report should stay concise:
- CHANGED: plan-only state/task/todo updates, no implementation.
- VERIFIED: budget gate block, guardian healthy, cron list ok.
- KPI/STATE: tokens/headroom, jobs skipped, gateway/rollback/concurrency/max_turns/human-approval state.
- BLOCKED/HUMAN ASK: only Tier B asks; none for ordinary low-headroom.
- NEXT ACTION: the next single Tier S control-plane slice when headroom recovers.
