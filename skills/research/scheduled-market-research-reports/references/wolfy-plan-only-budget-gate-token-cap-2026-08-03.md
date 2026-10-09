# Wolfy plan-only budget gate token cap — 2026-08-03

Session type: scheduled Wolfy daily optimizer run under the self-optimizing control-plane prompt.

## Trigger

At Phase 0, the deterministic budget gate blocked implementation:

```text
python3 wolfy/guardian/budget_gate.py --no-record
BUDGET=block token_cap_exceeded tokens_today=318509 cap=200000
exit=1
```

The correct response was PLAN-ONLY: orientation, guardian/probation review, Postgres task/run state, KPI updates, and ledger note only. No code/config/cron implementation was attempted.

## Verification shape that passed

- `python3 wolfy/guardian/config_guardian.py` returned `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;hermes_cron_list_ok;no_probation` exit 0.
- `hermes cron list` succeeded and still showed the optimizer, Jonah, and config guardian active.
- Created/claimed/completed `agent_tasks.id=3656` and `agent_runs.id=377516`.
- Recorded 22 `loop_metrics` rows, including `tokens_today=318509`, `usage_headroom_pct=0`, `jobs_skipped_by_budget=1`, `gateway_healthy=1`, `config_rollbacks=0`, `max_turns=90`, `parallel_jobs_cap=1`, `human_approval_pending=0`, and `regressions_introduced=0`.
- Left OWS-4 task `3546` queued for a future run with budget headroom.
- Appended the concise run note to `wolfy/optimization_todo.md` and committed locally as `1fa6c69`.

## Pitfalls discovered / reinforced

- Do not assume data-health helper views exist. In this run, `wolfy_ticker_data_load_status` was absent; KPI calculation needed to fall back to direct `prices` aggregation by ticker (`max(dt)`, bar count, >=500-bar depth) rather than aborting the plan-only run.
- Do not assume backtest metrics are stored in a `metrics` JSONB column. Current `backtests` has top-level columns including `survives_oos`, `is_sharpe`, `oos_sharpe`, `oos_cagr`, `max_dd`, and `turnover`.
- A failed psycopg statement aborts the transaction; verify that no partial `loop_metrics` rows landed before retrying. This run confirmed count 0 after each failed metric script before inserting the final 22 rows.
- The repo can contain earlier uncommitted daily ledger entries. Before committing, inspect the full staged diff. If earlier unverified entries are present in the same file, either verify/claim them explicitly or stage only the current hunk; avoid blindly `git add wolfy/optimization_todo.md`.

## Recommended next action

When budget headroom recovers, execute queued OWS-4 (`agent_tasks.id=3546`): reduce Jonah cadence from `*/20` to hourly under the Self-Modification Protocol.