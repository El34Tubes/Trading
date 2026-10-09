# Budget-gated optimizer plan-only closure

Use this when Wolfy's deterministic budget gate blocks an optimizer iteration before implementation.

## Required behavior

A budget block means **no implementation**: do not edit code, `config.yaml`, cron schedules, migrations, strategy status, or trading state. Still close the iteration durably rather than exiting without accounting.

1. Run `wolfy/guardian/budget_gate.py --no-record` and preserve its exact status/reason and nonzero exit.
2. Confirm guardian health, no unresolved probation, valid YAML/cron JSON, enabled optimizer and guardian jobs, successful `hermes cron list`, visible ledger, and Postgres requirements checks.
3. Persist a dedicated `agent_task` with a machine-checkable plan-only DoD; claim it, then start an `agent_run` linked to it.
4. Record the full KPI set in `loop_metrics`, one row per metric for the linked run. Include `jobs_skipped_by_budget=1`, current token/headroom values, guardian/gateway posture, and `regressions_introduced=0`.
5. Add only a concise dated entry to `wolfy/optimization_todo.md`: gate result, guardian/probation state, task/run IDs, lesson, and next action.
6. Stage only that ledger file, run `git diff --cached --check` and a staged secret scan, then make one local unpushed commit.
7. Store the full commit hash, verification result, and `verified_at` on the task **before** completing the task or finishing the run. Verify that metadata update succeeded, then perform the terminal state transitions.
8. Read back task/run terminal state and confirm KPI count equals distinct KPI-key count.

## Important distinctions

- A budget block is an implementation stop, not a failed iteration. If durable review/accounting DoD passes, task and run may finish `completed` with a clear `plan-only` summary.
- Do not create a duplicate implementation candidate each blocked day. Keep the existing queued control-plane task unchanged and create only the dated plan-only accounting task.
- Do not claim the queued implementation task while blocked.
- Metrics described as carried from a prior verified inventory must say so in `notes`; never label stale values as freshly measured.
- Fresh strategy KPI counts must use live Postgres status values. Recording metrics never authorizes changing a strategy to `approved`.

## CLI/SQL pitfalls

`wolfy_agent_cli.py task-ensure` does not accept `definition_of_done`; set the DoD with a targeted Postgres update after ensuring the task and before claiming it. Its success key is currently `AGENT_TASK_ID=<id>`, while `run-start` returns `AGENT_RUN_ID=<id>`; parse complete key/value lines rather than relying on a loose substring such as `TASK_ID=`. When issuing SQL through `psql -c`, do not assume `:variable` substitution works in every shell invocation; safely interpolate a numeric ID obtained from Postgres or feed SQL through stdin with explicit variable handling.

Inspect the live `loop_metrics` schema before writing accounting rows. Compatibility deployments may carry both `metric_key`/`metric_value` and `metric_name`/`value_numeric`, use `captured_at` rather than `recorded_at`, and expect both alias pairs to be populated. Insert the full KPI set in one transaction, delete only rows for the newly linked accounting run when making a retry idempotent, then verify both `count(*)` and `count(DISTINCT metric_name)` equal the required KPI-key count. Never delete unrelated guardian/system metrics.

When running multiple `psql` inputs, do not mix a `-c` query and a heredoc in one invocation and assume both execute. Use separate invocations or put all statements in the heredoc; otherwise later KPI probes can be silently skipped after the `-c` command completes.

Use the stable production guardian entrypoint for health checks: `bash scripts/wolfy_config_guardian.sh` from `/root/.hermes`. Do not guess convenience flags such as `config_guardian.py --check-only`; unsupported flags add error noise and can make a healthy guardian look broken. Require the wrapper's `GUARDIAN=ok` result, then verify `hermes cron status`, `hermes cron list`, and absence or resolution of `wolfy/guardian/probation.json` separately.

Derive strategy KPIs from canonical typed columns after inspecting the live schema. In particular, `strat_oos_complete` is `count(*) WHERE strategies.latest_oos_verdict IS NOT NULL`; do not query `metadata->'latest_oos_verdict'`, which may be absent while the authoritative boolean column is populated. Read the fresh count back and sanity-check it against the preceding run before terminalizing the accounting task.

Treat verification metadata persistence and task/run completion as a fail-closed sequence. If several commands share one shell call, begin with `set -e` (or gate each command explicitly); otherwise a failed metadata update can be followed by successful `task-complete` and `run-finish`, producing a terminal task whose verification fields are still empty. Prefer updating the canonical `verification_result`, `commit_hash`, and `verified_at` columns in one transaction, reading them back, and only then invoking completion commands. Avoid unnecessary JSONB payload merging in this critical path; if it is required, cast parameter types explicitly so PostgreSQL cannot raise `IndeterminateDatatype` for polymorphic JSON builders.

## Minimal completion report

Report only:

- **CHANGED** — durable task/run/KPI/ledger closure and explicit statement that no implementation occurred.
- **VERIFIED** — gate/guardian/config/cron/ledger/Postgres checks and unpushed commit hash.
- **KPI/STATE** — only notable values, especially headroom and budget skip.
- **BLOCKED/HUMAN ASK** — Tier B only; omit when none.
- **NEXT ACTION** — the single queued Tier S slice to execute after headroom recovers.
