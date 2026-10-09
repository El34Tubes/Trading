# Wolfy optimizer plan-only budget block — 2026-07-18

## Context
A scheduled Wolfy daily optimizer run started at 2026-07-18 02:15 ET. The budget gate was over cap, so the run had to remain PLAN-ONLY: review/state/KPI updates only, no code/config/cron/orchestration changes.

## Verified outputs
- `python3 wolfy/guardian/budget_gate.py --no-record` -> `BUDGET=block token_cap_exceeded tokens_today=332044 cap=200000`, exit `1`.
- `python3 wolfy/guardian/config_guardian.py` -> `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;hermes_cron_list_ok;no_probation`, exit `0`.
- `hermes cron list` -> exit `0`; optimizer job `92f31b95fccc` active.
- `python3 scripts/visible_progress_ledger.py --json` -> exit `0`.
- Postgres task `3575` and run `322840` were completed; `loop_metrics` rows for the run totaled `24`.
- Local commit: `588eaf3` (`wolfy(opt): record plan-only budget block — DoD met (task 3575)`).

## Durable pattern
1. If budget gate blocks, do not implement Tier S work, even if a queued orchestration task exists.
2. Persist a plan-only `agent_task`, claim it, and start an `agent_run`.
3. Update `optimization_todo.md` with the real budget/guardian/cron outputs.
4. Insert KPI rows into `loop_metrics` and verify the count before declaring DoD.
5. Only then complete the task/run and commit the durable ledger note.

## Pitfalls found
- Do not invent flags for the guardian/gate scripts. `budget_gate.py --json` and `config_guardian.py --health --json` are unsupported; use the supported bare/`--no-record`/`--skip-cli` paths described in the skill.
- When using `psycopg.connect(..., row_factory=dict_row)`, `fetchone()` results are dict-like; use named keys (`row['lag']`) rather than numeric indexes (`row[0]`). A numeric index raised `KeyError: 0` during metric insertion.
- Do not mark the task/run complete before metrics are inserted and verified. If an insertion script fails after task completion, rerun/fix the metric insertion and then update task/run metadata so the stored DoD matches actual verification.

## Next action carried forward
When budget headroom recovers, execute exactly one Tier S control-plane slice. Preferred queued task remains `3546` / OWS-4: reduce Jonah cadence from `*/20` to hourly under the self-modification protocol; otherwise finish remaining OWS-1 no-op coverage if budget-gate gaps are higher leverage.
