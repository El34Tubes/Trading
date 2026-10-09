# Wolfy plan-only optimizer budget block — 2026-07-19

Use this as a compact reference for future Wolfy self-optimizing cron iterations that start over the LLM token cap.

## Situation

- Scheduled optimizer ran at ~2026-07-19 02:15 ET.
- `python3 wolfy/guardian/budget_gate.py` returned `BUDGET=block token_cap_exceeded tokens_today=256523 cap=200000` with exit `1`.
- Per the optimizer constitution, this forced PLAN-ONLY mode: deterministic orientation/review/state/KPI updates only; no code/config/cron implementation and no new orchestration probation.

## Commands that mattered

```bash
python3 wolfy/guardian/budget_gate.py
# BUDGET=block token_cap_exceeded tokens_today=256523 cap=200000
# exit 1

python3 wolfy/guardian/config_guardian.py
# GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;hermes_cron_list_ok;no_probation
# exit 0

hermes cron list
# succeeded; optimizer job 92f31b95fccc remained active, next run 2026-07-20T02:15:00-04:00
```

## Durable state pattern

- Created/claimed/completed `agent_tasks` row `3576` and `agent_runs` row `326692`.
- Inserted 25 `loop_metrics` rows for the run, including:
  - `tokens_today=256523`
  - `usage_headroom_pct=0`
  - `jobs_skipped_by_budget=1`
  - `gateway_healthy=1`
  - `parallel_jobs_cap=1`
- Updated `agent_tasks.definition_of_done` with a machine-checkable PASS summary because the active schema has no `verification_result`, `commit_hash`, or `verified_at` columns.
- Updated `/root/.hermes/wolfy/optimization_todo.md` with a terse plan-only entry and committed only that file locally: `e4d1d22`.

## Pitfalls / schema notes

- `budget_gate.py` does not accept `--json`; use plain output, or `--no-record` when you need a non-metric-writing check.
- `config_guardian.py` does not accept `--health --json`; use plain `python3 wolfy/guardian/config_guardian.py` or `--skip-cli`.
- `agent_tasks` in the current schema lacks `verification_result`, `commit_hash`, and `verified_at`; store verification in `definition_of_done` and/or JSONB `metadata`/`payload` rather than querying nonexistent columns.
- The Postgres `universe` view uses `symbol` as the ticker column; join it to `prices.ticker` with `symbol AS ticker` when computing freshness/depth KPIs.
- `loop_metrics` should be written/read by `metric_key`; compatibility aliases may exist, but `metric_key` is the canonical column.
- In a dirty repo, commit ledger-only updates by staging the exact intended path and verify `git log -1 --oneline -- wolfy/optimization_todo.md`; avoid pulling unrelated curator/profile/autorepair changes into the commit.

## Next action preserved

When budget headroom recovers, execute exactly one Tier S control-plane slice. Preferred queued task remains `3546` / OWS-4: reduce Jonah cadence from `*/20` to hourly under the self-modification protocol; otherwise finish remaining OWS-1 no-op coverage if budget-gate gaps are found.
