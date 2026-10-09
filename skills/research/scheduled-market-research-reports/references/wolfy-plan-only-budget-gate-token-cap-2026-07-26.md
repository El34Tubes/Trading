# Wolfy plan-only budget gate token-cap run — 2026-07-26

Use this reference for daily Wolfy optimizer runs where the proactive budget gate blocks implementation but durable state should still advance.

## Trigger

- Scheduled optimizer run at 02:15 ET.
- `python3 wolfy/guardian/budget_gate.py --no-record` returned:
  - `BUDGET=block token_cap_exceeded tokens_today=256305 cap=200000`
  - exit `1`
- Per Wolfy optimizer rules, this requires PLAN-ONLY: deterministic orientation/review/state/KPI only; no code/config/cron/orchestration implementation.

## Successful bounded pattern

1. Run deterministic checks first:
   - budget gate with `--no-record`
   - `python3 wolfy/guardian/config_guardian.py --skip-cli`
   - `hermes cron list`
2. Create or dedupe a plan-only `agent_tasks` row with a stable fingerprint, e.g. `wolfy-optimizer-plan-only-budget-block-YYYY-MM-DD`.
3. Start a matching `agent_runs` row and bind it to the task.
4. Record KPI rows under the current run:
   - `tokens_today`
   - `usage_headroom_pct`
   - `jobs_skipped_by_budget=1`
   - `gateway_healthy`
   - `config_rollbacks`
   - `max_turns`
   - `parallel_jobs_cap`
   - `human_approval_pending`
   - `regressions_introduced`
5. Mark the task/run completed only if durable state actually changed and verification output exists. Use `blocked` if no durable progress was made.
6. Append a short dated entry to `wolfy/optimization_todo.md` if allowed and commit only that intended file after checking the staged diff.
7. Store the local commit hash back onto `agent_tasks.commit_hash` if that compatibility column exists.

## Verification outputs from this run

- Guardian: `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;no_probation`.
- Cron: `hermes cron list` succeeded; optimizer job `92f31b95fccc` stayed active with next run `2026-07-27T02:15:00-04:00`.
- Task/run: task `3607` completed; run `353572` completed.
- Metrics: 9 `loop_metrics` rows recorded for run `353572`.
- Commit: `49baf36 wolfy(opt): record budget-block plan-only run — DoD met (task 3607)`.

## Pitfalls reinforced

- Do not attempt OWS-4 or any config/schedule edit while `BUDGET=block`.
- Do not commit broad dirty workspace changes. Stage only the verified ledger/doc file for a plan-only commit.
- `agent_runs` uses `error_message`, not `error`; avoid orientation queries that assume an `error` column.
- The repo may contain many unrelated dirty files from curator/profile/autorepair jobs; treat them as out of scope for the optimizer run.
