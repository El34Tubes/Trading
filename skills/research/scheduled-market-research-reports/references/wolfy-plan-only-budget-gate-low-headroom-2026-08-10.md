# Wolfy plan-only budget gate low-headroom run — 2026-08-10

Use this as a concrete reference for Wolfy daily optimizer runs where `budget_gate.py` blocks on low headroom and the run must stay plan-only.

## Trigger

- Cron job: `Wolfy daily optimization planner and implementer` (`92f31b95fccc`), schedule `15 2 * * *`.
- Budget check: `python3 wolfy/guardian/budget_gate.py --no-record` returned `BUDGET=block low_headroom_pct=14.65 threshold=15.00` with exit `1`.
- Result: no code/config/cron implementation and no self-modification protocol action.

## Safe actions performed

1. Ran deterministic orientation only: date/ET time, git status, `hermes cron list`, process snapshot, guardian/budget checks, visible ledger, open `agent_tasks`, probation marker, and optimization ledger tail.
2. Verified guardian/probation state with `python3 wolfy/guardian/config_guardian.py --skip-cli` -> `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;no_probation` exit `0`.
3. Queried `agent_runs` token sum directly because the low-headroom budget-gate line did not include `tokens_today`; value was `170706`, corresponding to `usage_headroom_pct=14.65` against cap `200000`.
4. Created/claimed/completed a plan-only `agent_tasks` row (`3750`) and an `agent_runs` row (`385599`).
5. Recorded 19 `loop_metrics` rows, including budget skip, guardian/config state, loop health, strategy counts, and repo health.
6. Updated `/root/.hermes/wolfy/optimization_todo.md` with the daily plan-only entry.
7. Made a narrow verified local commit of only the ledger file: `62d3248 wolfy(opt): record 2026-08-10 plan-only budget run — DoD met (task 3750)`.
8. Backfilled `agent_tasks.commit_hash='62d3248'` after the commit.

## Verification outputs to reproduce the pattern

- `python3 wolfy/guardian/budget_gate.py --no-record` -> `BUDGET=block low_headroom_pct=14.65 threshold=15.00`, exit `1`.
- `python3 wolfy/guardian/config_guardian.py --skip-cli` -> `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;no_probation`, exit `0`.
- `test ! -f wolfy/guardian/probation.json` -> exit `0`.
- `hermes cron list` succeeded; optimizer remained active with next run `2026-08-11T02:15:00-04:00`.
- Postgres checks confirmed:
  - task `3750` status `completed`, `commit_hash=62d3248`, `verified_at` present.
  - run `385599` status `completed`, `records_created=19`, `ended_at` present.
  - `count(*) from loop_metrics where run_id=385599` -> `19`.

## Pitfalls reinforced

- `budget_gate.py --no-record` low-headroom output may omit `tokens_today`; query today's token sum from `agent_runs` before recording KPIs.
- Do not treat a budget-blocked plan-only run as a failure when it performs durable state/metric/ledger updates; complete the task/run with an explicit plan-only summary.
- In a dirty Hermes repo, stage only the intended verified file before committing. This run committed only `wolfy/optimization_todo.md`.
- After committing, update the task's `commit_hash`; if you set verification metadata before the commit, remember to backfill the actual hash afterward.
- Use the cron final response for delivery; do not call messaging tools from the scheduled job.
