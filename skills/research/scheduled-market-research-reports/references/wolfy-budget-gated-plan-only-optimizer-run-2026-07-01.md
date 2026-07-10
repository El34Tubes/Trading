# Wolfy budget-gated plan-only optimizer run (2026-07-01)

Use this when the Wolfy self-optimizing daily cron starts while the proactive budget gate blocks LLM work.

## Trigger

- `python wolfy/guardian/budget_gate.py` prints `BUDGET=block ...` and exits non-zero.
- The prompt/rules say low budget headroom means **PLAN-ONLY**: orient, review, update durable state, report, and stop without implementation.

Concrete session signal:

```text
BUDGET=block codex_usage_limited
budget_exit=1
```

## Correct response pattern

1. Still complete deterministic orientation cheaply: `hermes cron list`, guardian health, probation marker, visible ledger, open `agent_tasks`, recent runs/metrics.
2. Do **not** modify code, config, cron schedules, or LLM-job enablement while the gate blocks. This includes not attempting the next OWS implementation slice.
3. Persist a small plan-only `agent_task` and `agent_run` so the loop is auditable. Example shape:
   - `task-ensure` title like `Plan-only optimizer iteration under budget gate`.
   - `task-claim` with a run-specific claim token.
   - `run-start` / `run-finish --status completed` because the plan-only DoD was satisfied.
4. Record `loop_metrics`, at minimum:
   - `jobs_skipped_by_budget=1`
   - `parallel_jobs_cap` if verified from config
   - `human_approval_pending`
   - `config_rollbacks` if relevant
5. Update `/root/.hermes/wolfy/optimization_todo.md` with a short dated note: budget status, guardian/probation state, what metrics/tasks/runs were recorded, and the next action after budget recovers.
6. Final cron response should stay concise: `CHANGED`, `VERIFIED`, `KPI/STATE`, `BLOCKED/HUMAN ASK`, `NEXT ACTION`.

## Probation nuance

If an orchestration/config change is still on probation, do not make another config/schedule/orchestration change. Report that probation is active and wait for the next eligible run/guardian cycle to promote or roll back it.

Concrete marker from this session:

```json
{
  "change": "OWS-3 concurrency governor: cron.max_parallel_jobs=1; kanban.max_in_progress_per_profile=1",
  "snapshot_path": "/root/.hermes/wolfy/guardian/known_good/20260701T012621Z",
  "expires_at": "2026-07-01T06:30:00Z"
}
```

## Verification commands used

- `python wolfy/guardian/budget_gate.py` → block exit, plan-only.
- `python wolfy/guardian/config_guardian.py --skip-cli` → `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;probation_active`.
- `hermes cron list` → exit 0.
- YAML config readback for `cron.max_parallel_jobs=1` and `kanban.max_in_progress_per_profile=1`.
- Postgres queries confirming the plan-only task/run completed and metrics were inserted.

## Reporting pitfall

`config_rollbacks` counted over a recent window may include guardian/self-test rollback proofs rather than production regressions. Label it as the windowed recorded metric, not necessarily a new live failure introduced by the optimizer run.
