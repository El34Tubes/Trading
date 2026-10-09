# Wolfy plan-only budget gate token-cap run — 2026-08-04

## When to use

Use this reference for Wolfy's daily self-optimizing cron when `wolfy/guardian/budget_gate.py` blocks implementation because today's autonomous LLM token budget is already over cap.

## Observed pattern

- Time: 2026-08-04 02:15 EDT / 06:15 UTC.
- `python3 wolfy/guardian/budget_gate.py --no-record` printed `BUDGET=block token_cap_exceeded tokens_today=286836 cap=200000` and exited `1`.
- The correct response was PLAN-ONLY: deterministic orientation/review, guardian + cron checks, task/run/metric persistence, ledger note, final concise report, and **no code/config/cron implementation**.
- Guardian check command is plain `python3 wolfy/guardian/config_guardian.py` (or `--skip-cli` for cheaper checks), not nonexistent JSON/health flags. It returned `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;hermes_cron_list_ok;no_probation`.
- `hermes cron list` succeeded and optimizer job `92f31b95fccc` remained active.
- No probation marker existed.

## Durable-state pattern

- Create/claim a plan-only `agent_tasks` row via `wolfy_agent_cli.py task-ensure` + `task-claim`.
- Start an `agent_runs` row via `run-start` and finish it as `completed` if durable state was updated, even though implementation was skipped.
- Store task verification in task fields (`definition_of_done`, `verification_result`, `verified_at`), not `agent_runs.verification_result`.
- Insert `loop_metrics` rows for at least: `tokens_today`, `usage_headroom_pct=0`, `jobs_skipped_by_budget=1`, `gateway_healthy=1`, `config_rollbacks=0`, `max_turns`, `parallel_jobs_cap`, `human_approval_pending`, `regressions_introduced`, and useful repo/migration/strategy state.
- If the only repository change is the daily ledger entry in `wolfy/optimization_todo.md`, a narrow local commit is acceptable after verifying staged paths. This run committed only the ledger update as `54b7e34`.

## Verification commands that passed

```bash
python3 wolfy/guardian/budget_gate.py --no-record
python3 wolfy/guardian/config_guardian.py
hermes cron list
python3 wolfy/visible_progress_ledger.py --json
psql "$WOLFY_POSTGRES_DSN" -c "select id,status,verified_at,verification_result from agent_tasks where id=<task_id>;"
psql "$WOLFY_POSTGRES_DSN" -c "select id,status,records_created,input_tokens,output_tokens from agent_runs where id=<run_id>;"
psql "$WOLFY_POSTGRES_DSN" -c "select count(*) from loop_metrics where run_id=<run_id>;"
git status --porcelain=v1 -- wolfy/optimization_todo.md
git diff --cached --name-only
```

## Pitfalls reinforced

- Do not try `budget_gate.py --json`; that flag does not exist.
- Do not try `config_guardian.py --health --json`; those flags do not exist.
- Parse `cron/jobs.json` defensively as either a dict with `jobs` or a bare list.
- The repo is usually dirty from unrelated curator/profile/autorepair changes. Stage only the intended ledger hunk/file and inspect `git diff --cached` before committing.
- A budget-gated plan-only run can still be a successful optimizer iteration if it records durable task/run/metric state and leaves a concrete next action.
