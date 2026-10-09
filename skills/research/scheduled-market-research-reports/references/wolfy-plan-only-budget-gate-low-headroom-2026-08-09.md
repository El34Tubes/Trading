# Wolfy plan-only budget-gate low-headroom run — 2026-08-09

## Context

The daily Wolfy optimizer ran as a scheduled cron job with the self-optimizing control-plane prompt active. The proactive budget gate reported low headroom, so the run had to be PLAN-ONLY: orient, verify guardian/cron state, persist task/run/KPI state, and avoid implementation or config/schedule changes.

## Commands and outputs worth preserving

- `python wolfy/guardian/budget_gate.py --no-record` -> `BUDGET=block low_headroom_pct=10.15 threshold=15.00` (exit 1).
- `python wolfy/guardian/config_guardian.py --skip-cli` -> `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;no_probation` (exit 0).
- `hermes cron list` succeeded and optimizer job `92f31b95fccc` remained active.
- Created/claimed/completed Postgres task `3749` and run `384507`.
- Recorded 22 `loop_metrics` rows, including `jobs_skipped_by_budget=1`, `tokens_today=179698`, `usage_headroom_pct=10.151`, `gateway_healthy=1`, `config_rollbacks=0`, `max_turns=90`, `parallel_jobs_cap=1`, and `human_approval_pending=0`.
- Appended a concise ledger entry to `wolfy/optimization_todo.md` and committed only that verified ledger update: `7ce0d1ce36f2758dd35a6c00232ae0576767280a`.

## Pitfalls discovered/reinforced

1. Do not call unsupported structured flags on the current guardian scripts: `budget_gate.py` has no `--json`; `config_guardian.py` has no `--health --json`. Use plain output and `--no-record` / `--skip-cli` as appropriate.
2. If a multi-statement metric/task write fails, do not immediately run `task-complete` / `run-finish` in the same shell chain. In this run, an initial metrics script failed on a schema/search-path query but the subsequent completion commands still ran. Recovery required verifying the task/run rows, rerunning the KPI/DoD update, then re-verifying. Future plan-only runs should split write steps or run with `set -euo pipefail` so completion only happens after KPI/DoD writes succeed.
3. Prefer schema-qualified `public.prices` for direct data-health SQL inside ad-hoc Python scripts, and verify columns before assuming search-path behavior.
4. `loop_metrics` canonical inserts should use `metric_key`; compatibility aliases (`metric_name`, `value_numeric`, `created_at`) may need to be populated for older probes.
5. If committing during a dirty Wolfy repo, stage only the intended ledger hunk/file and verify `git log -1 --oneline -- <file>` plus Postgres `commit_hash` on the task. Do not push from the optimizer.

## Report shape used

Final cron report stayed concise:

- `CHANGED`: plan-only budget block, Postgres state, ledger commit.
- `VERIFIED`: budget gate, guardian, cron, metric count, commit hash.
- `KPI/STATE`: only notable values.
- `BLOCKED/HUMAN ASK`: none.
- `NEXT ACTION`: wait for budget headroom, then OWS-4/Jonah hourly cadence under self-modification protocol.
