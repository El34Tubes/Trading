# Wolfy plan-only optimizer budget gate — low headroom (2026-08-08)

Use this as a concrete reference for Wolfy's daily self-optimizing loop when `budget_gate.py` blocks implementation for low headroom but durable plan-only progress is still expected.

## Trigger

- Scheduled optimizer job: `92f31b95fccc` (`15 2 * * *`).
- `python3 wolfy/guardian/budget_gate.py --no-record` returned:
  - `BUDGET=block low_headroom_pct=6.50 threshold=15.00`
  - exit `1`.
- Therefore the run stayed PLAN-ONLY: deterministic orientation/review, task/run/KPI state, ledger update, no code/config/cron implementation.

## Verified sequence

1. Orient with cheap deterministic probes:
   - ET/UTC time.
   - `git status --porcelain`.
   - `hermes cron list` and confirm optimizer still active.
   - process list / gateway process present.
   - `python3 wolfy/guardian/config_guardian.py --skip-cli`.
   - `python3 wolfy/visible_progress_ledger.py --json`.
   - Postgres `agent_tasks`, `agent_runs`, and `loop_metrics` schema/state.
2. If `budget_gate.py` low-headroom output does not include `tokens_today`, compute it before KPI insert. In this run, importing `budget_gate.tokens_today(conn)` produced `tokens_today=187001` and `usage_headroom_pct=6.4995` against the 200k cap.
3. Use `wolfy_agent_cli.py task-ensure`, not nonexistent `task-create`:
   - created task `3746` with fingerprint `wolfy-optimizer-plan-only-2026-08-08`.
   - set `definition_of_done` with a direct Postgres `UPDATE`.
   - claimed it with `task-claim`.
   - started run `383439` with `run-start`.
4. Record loop metrics tied to the run id. This run inserted 13 rows:
   - `tokens_today`, `usage_headroom_pct`, `jobs_skipped_by_budget`, `gateway_healthy`, `config_rollbacks`, `max_turns`, `parallel_jobs_cap`, `active_cron_jobs`, `jonah_cadence_minutes`, `human_approval_pending`, `queued_tasks`, `iteration_success_rate`, `regressions_introduced`.
5. Update only `wolfy/optimization_todo.md`; no code/config/cron change while budget-blocked.
6. Commit only the verified ledger hunk/file after inspecting the staged path:
   - commit `8ca854e20ed651d66d4ed55f999bcea0b3e4339b`.
7. Store verification on `agent_tasks` (`verification_result`, `commit_hash`, `verified_at`), complete task, and finish run:
   - task `3746` completed.
   - run `383439` completed with `records_created=13`.

## Pitfalls reinforced

- `agent_runs` has `error_message`, not `error`; do not query `agent_runs.error`.
- `budget_gate.py --no-record` can block without printing token count; query tokens separately before recording KPI rows.
- The repo is commonly dirty from unrelated curator/profile/autorepair work. Stage only the intended ledger file/hunk before committing.
- A low-headroom plan-only run can be marked `completed` if it records durable state and verifies DoD; use `blocked` only when no durable progress was made.
- Do not start OWS-4 or any config/schedule change while budget gate says block, even if the next task is queued and obvious.

## Next action preserved

Queued task `3546` remains the preferred next Tier S item when headroom recovers: OWS-4, reduce Jonah cadence from `*/20` to hourly under the Self-Modification Protocol.
