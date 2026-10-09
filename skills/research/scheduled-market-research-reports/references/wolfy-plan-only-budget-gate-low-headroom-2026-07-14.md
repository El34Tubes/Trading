# Wolfy plan-only budget gate low-headroom run — 2026-07-14

## Context

The daily Wolfy optimizer ran under the self-optimizing control-plane prompt after OWS-1/OWS-2 guardian work existed. At Phase 0, the deterministic budget gate reported very low headroom, so the optimizer correctly switched to PLAN-ONLY and avoided code/config/cron changes.

## Durable pattern

When `wolfy/guardian/budget_gate.py --no-record` emits a block such as:

```text
BUDGET=block low_headroom_pct=0.92 threshold=15.00
```

then:

1. Do deterministic orientation/review only: ET/UTC time, git status, `hermes cron list`, process snapshot, guardian checks, ledger/open-task/probation inspection.
2. Do **not** apply Tier S implementation, config changes, schedule changes, or LLM-job enablement changes.
3. Verify guardian health with the actual current CLI:
   - `python wolfy/guardian/config_guardian.py --skip-cli`
   - expect `GUARDIAN=ok ...`
4. Persist minimal durable state in Postgres:
   - start/finish an `agent_runs` row for the optimizer;
   - record `loop_metrics` such as `usage_headroom_pct`, `jobs_skipped_by_budget=1`, `gateway_healthy`, `parallel_jobs_cap`, `max_turns`, `human_approval_pending`, and `regressions_introduced=0`.
5. Leave the next concrete task queued with a machine-checkable DoD instead of doing it. In this run, OWS-4 (`Right-size Jonah cadence outlier`) remained queued as task `3546`.
6. Send a concise final report: CHANGED, VERIFIED, KPI/STATE, BLOCKED/HUMAN ASK, NEXT ACTION.

## CLI/schema pitfalls confirmed

- `budget_gate.py` does **not** accept `--status`; use `--no-record` for a no-extra-write check.
- `config_guardian.py` does **not** accept `--status`; use `--skip-cli` for a lightweight health check.
- `loop_metrics` columns are `metric_key` and `metric_value`, not `metric_name`.
- Current `agent_runs` completion can record `records_created` for metrics inserted; use `run-finish --status completed` when the plan-only state/metrics write succeeded.

## Verification outputs from the run

```text
python wolfy/guardian/budget_gate.py --no-record
BUDGET=block low_headroom_pct=0.92 threshold=15.00
EXIT:1

python wolfy/guardian/config_guardian.py --skip-cli
GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;no_probation
EXIT:0

hermes cron list
HERMES_CRON_LIST_OK
```

No local commit was made because there were no verified source/config changes in this run.
