# Wolfy optimizer: token-cap plan-only ledger pattern (2026-08-13)

Use this when the deterministic optimizer budget gate blocks because the daily token cap is exhausted, while the scheduler and guardian remain healthy.

## Proven sequence

1. Run the production-home checks explicitly:
   - `python3 wolfy/guardian/budget_gate.py --no-record`
   - `python3 wolfy/guardian/config_guardian.py --home /root/.hermes --skip-cli`
   - `hermes --profile default cron list --all`
   - `hermes --profile default cron status`
   - `python3 wolfy/visible_progress_ledger.py --json`
2. Treat `BUDGET=block token_cap_exceeded ...` as a hard implementation stop. Do not modify code, config, cron, migrations, guardian files, or strategy status.
3. Persist a dedicated plan-only `agent_task` with a machine-checkable DoD, claim it, and create an associated `agent_run`.
4. Record `loop_metrics` against that exact run ID. At minimum capture budget/token state, budget skip count, gateway/guardian posture, concurrency caps, regression count, human-approval count, and notable strategy/data posture.
5. Verify the metric row count before completing the task or run. With psycopg mapping rows, access values by column name rather than tuple index.
6. Add a concise durable entry to `wolfy/optimization_todo.md` containing the exact gate result, guardian/cron result, task/run IDs, one reusable lesson, and the retained next action.
7. In a dirty live-state repository, stage and commit only the intended ledger file. Store the real commit hash and verification result on the task, then complete the task and run.
8. Final verification should prove:
   - task is `completed` and has `commit_hash`, `verification_result`, and `verified_at`;
   - run is `completed`, linked to the task, and has the actual metric count in `records_created`;
   - expected `loop_metrics` rows exist for the run;
   - the ledger file is clean after commit;
   - no stale unrelated `agent_runs.status='started'` rows were introduced.

## Example observed result

- Budget gate: `BUDGET=block token_cap_exceeded tokens_today=203455 cap=200000`, exit 1.
- Guardian: `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;no_probation`, exit 0.
- Gateway: running; 28 active jobs.
- Durable state: task `3877`, run `388738`, 15 metric rows.
- Local unpushed ledger commit: `d80d28e`.

The IDs and counts above are historical evidence, not constants for future runs.