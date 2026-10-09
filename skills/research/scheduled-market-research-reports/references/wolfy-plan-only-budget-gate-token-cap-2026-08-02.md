# Wolfy plan-only budget gate token cap — 2026-08-02

## Trigger

The daily Wolfy optimizer ran under the self-optimizing loop prompt. Phase 0 orientation showed the proactive budget gate over cap:

```text
python wolfy/guardian/budget_gate.py --no-record
BUDGET=block token_cap_exceeded tokens_today=203183 cap=200000
EXIT=1
```

Per the Wolfy optimizer contract, this forces PLAN-ONLY: deterministic review/state/KPI updates are allowed, but no code/config/cron implementation or self-modification should occur.

## What worked

- Used `config_guardian.py --skip-cli` for a cheap guardian check:
  ```text
  GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;no_probation
  EXIT=0
  ```
- Still verified core orchestration facts cheaply: `hermes cron list` succeeded, no probation marker existed, and `config.yaml` / `cron/jobs.json` parsed.
- Created and claimed a durable plan-only `agent_task` with `wolfy_agent_cli.py task-ensure` / `task-claim` instead of a nonexistent task-create command.
- Started and completed `agent_runs` row `376346` and completed task `3655` after verifying rows.
- Inserted 18 `loop_metrics` rows for the run, including `jobs_skipped_by_budget=1`, `tokens_today=203183`, `usage_headroom_pct=0`, `gateway_healthy=1`, `config_rollbacks=0`, `max_turns=90`, `parallel_jobs_cap=1`, `human_approval_pending=0`, and `regressions_introduced=0`.
- Updated `wolfy/optimization_todo.md` with the daily plan-only entry.

## Pitfalls / durable lessons

- Budget-gate `BUDGET=block token_cap_exceeded ...` is a hard stop for Tier S implementation, not merely a warning. Do not reduce Jonah cadence, edit cron/config, commit code, or touch orchestration when this fires.
- A failed psycopg statement leaves the current transaction aborted/rolled back. If a metrics insert script fails mid-run, rerun the corrected insertion and then verify `loop_metrics` row count before completing task/run state.
- Postgres date arithmetic can differ from expected interval handling. For price freshness lag, `(current_date - max(dt))::int` works when `dt` is a date; `extract(day from current_date - max(dt))` can fail because the subtraction returns an integer, not an interval.
- `optimization_todo.md` may already contain unrelated unstaged entries from earlier runs. Patch only the intended new daily section; do not overwrite or restage unrelated dirty workspace changes.
- In dirty Hermes/Wolfy repos, a verified plan-only ledger update does not require a commit if it would risk staging unrelated profile/skill/autorepair changes. Report “no commit” honestly.

## Recommended final report shape

Use the concise cron-delivered format:

```text
CHANGED
- Budget gate blocked implementation: tokens_today=203183 exceeded cap 200000, so this was PLAN-ONLY.
- Created/claimed/completed Postgres task 3655; completed run 376346.
- Updated optimization_todo.md with today’s plan-only ledger entry.

VERIFIED
- budget_gate.py --no-record -> BUDGET=block ..., exit 1.
- config_guardian.py --skip-cli -> GUARDIAN=ok ..., exit 0.
- hermes cron list succeeded; config.yaml and cron/jobs.json parsed.
- No local commit: no implementation/config/cron change was allowed under low budget.

KPI/STATE
- Recorded loop_metrics rows and key metrics.

BLOCKED/HUMAN ASK
- None.

NEXT ACTION
- When budget headroom recovers, execute exactly one Tier S slice: queued task 3546 / OWS-4 Jonah cadence hourly under the self-modification protocol.
```
