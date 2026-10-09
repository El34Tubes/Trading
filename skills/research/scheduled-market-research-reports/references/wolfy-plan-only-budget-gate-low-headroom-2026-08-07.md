# Wolfy plan-only optimizer run — low headroom (2026-08-07)

## Trigger

The daily Wolfy optimizer started at 2026-08-07 02:15 ET. The proactive budget gate returned:

```text
BUDGET=block low_headroom_pct=3.37 threshold=15.00
exit=1
```

Because this was a low-headroom budget block, the run stayed PLAN-ONLY: deterministic orientation/review/state/KPI updates only, with no code/config/cron implementation.

## Useful command pattern

- Budget check: `python3 wolfy/guardian/budget_gate.py --no-record; printf 'exit=%s\n' $?`
- Guardian check: `python3 wolfy/guardian/config_guardian.py --skip-cli; printf 'exit=%s\n' $?`
- Cron health: `hermes cron list` and grep the optimizer job `Wolfy daily optimization planner and implementer` / `92f31b95fccc`.
- If budget-gate output lacks `tokens_today` (common for `low_headroom_pct`), compute it from today's `agent_runs` token sum before recording KPIs.

## CLI/schema pitfall found

`wolfy_agent_cli.py task-ensure` prints `AGENT_TASK_ID=<id>`, not `TASK_ID=<id>`. Do not parse only `TASK_ID=` or task creation will succeed while downstream DoD update/claim/run-start code gets an empty ID. Parse either key, or use the known ID from the printed output.

The current run/task bookkeeping flow that worked:

1. `wolfy_agent_cli.py task-ensure ...` → `AGENT_TASK_ID=3739`.
2. Update `agent_tasks.definition_of_done` directly in Postgres.
3. `wolfy_agent_cli.py task-claim --source-fingerprint ... --claim-token ... --fail-if-none`.
4. `wolfy_agent_cli.py run-start --agent wolfy-optimizer --role orchestrator --job-id 92f31b95fccc --task-id 3739` → `AGENT_RUN_ID=382295`.
5. Insert `loop_metrics` rows with `run_id=382295`.
6. Patch `optimization_todo.md` with a concise daily entry.
7. `task-complete`, `run-finish`, then store `commit_hash`/`verification_result`/`verified_at` in `agent_tasks`.

## Verification/output

- `config_guardian.py --skip-cli` returned `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;no_probation`.
- `hermes cron list` succeeded; optimizer remained active with next run `2026-08-08T02:15:00-04:00`.
- Postgres task `3739` and run `382295` were completed.
- `loop_metrics` rows for run `382295`: 15.
- Local commit: `f9219c4f991d82d1ee5a50beb3ca08606dc3b148`.

## Commit hygiene lesson

The repository was very dirty from unrelated profile/curator/runtime files. Even for a ledger-only plan run, inspect staged paths before committing. If earlier uncommitted entries exist in the same ledger, decide explicitly whether they are intended to be included; otherwise stage only the current hunk with a minimal cached patch.
