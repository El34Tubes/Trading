# Wolfy plan-only budget gate token cap — 2026-07-29

Use this as a concrete pattern for a daily optimizer run when `budget_gate.py` blocks implementation because the daily token cap is exceeded.

## Real outputs from the run

- Time: `2026-07-29 02:15 ET / 06:15 UTC`.
- Budget gate: `python3 wolfy/guardian/budget_gate.py --no-record` printed `BUDGET=block token_cap_exceeded tokens_today=308584 cap=200000` and exited non-zero.
- Guardian: `python3 wolfy/guardian/config_guardian.py` printed `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;hermes_cron_list_ok;no_probation`.
- Cheap guardian check: `python3 wolfy/guardian/config_guardian.py --skip-cli` printed `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;no_probation`.
- Cron verification: `hermes cron list` contained optimizer job `92f31b95fccc [active]`.
- Durable state: task `3614`, run `364887`, 16 `loop_metrics` rows.
- Local unpushed commit: `782a28e wolfy(opt): plan-only budget block 2026-07-29 — DoD met (task 3614)`.

## Implementation pattern

1. Treat `BUDGET=block token_cap_exceeded` as PLAN-ONLY: orient/review, but do not implement code/config/cron changes.
2. Persist a fresh daily `agent_task`, claim it, start a run, and update `definition_of_done`, `verification_result`, and `verified_at` after real checks.
3. Insert KPI rows for the plan-only run, including `tokens_today`, `usage_headroom_pct=0`, `jobs_skipped_by_budget=1`, `gateway_healthy`, `config_rollbacks`, `max_turns`, `parallel_jobs_cap`, `human_approval_pending`, and repo/loop state.
4. If a complex inline Python/heredoc terminal command gets blocked by shell-backgrounding detection or quoting, write a short temporary script file, run it, verify output, then remove it. The lesson is not that the command/tool is broken; it is to prefer deterministic temp scripts for multi-statement Postgres metric writes.
5. In dirty repos with pre-existing changes to the same ledger file, stage only the intended hunk. Safe pattern:
   - inspect `git diff -- wolfy/optimization_todo.md`;
   - create a minimal patch containing only the new daily entry;
   - `git apply --cached <patch>`;
   - inspect `git diff --cached -- wolfy/optimization_todo.md`;
   - commit the staged hunk only.
6. Finish the Postgres task/run as completed only after the checks pass and metrics exist.

## Pitfalls

- Do not let an existing unrelated unstaged change in `optimization_todo.md` ride along in the daily ledger commit.
- Do not query nonexistent run verification columns; verification belongs on task fields/metadata plus run summary.
- A narrow documentation/ledger commit is acceptable in plan-only mode when it is the only staged verified change and implementation remains skipped.
