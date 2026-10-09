# Wolfy plan-only optimizer run: token cap exceeded (2026-07-23)

Use this as a concrete reference for Wolfy's daily self-optimizing loop when the budget gate blocks implementation because the daily token cap is already exceeded.

## Observed deterministic orientation

- Time anchor: `2026-07-23 02:15 ET / 06:15 UTC`.
- Budget check: `python3 wolfy/guardian/budget_gate.py --no-record` returned:
  - `BUDGET=block token_cap_exceeded tokens_today=280041 cap=200000`
  - exit code `1`.
- Guardian check: `python3 wolfy/guardian/config_guardian.py` returned:
  - `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;hermes_cron_list_ok;no_probation`
  - exit code `0`.
- `hermes cron list` succeeded and showed optimizer `92f31b95fccc`, Jonah, and config guardian active.
- No probation marker existed.

## Correct run behavior

Because the budget gate blocked headroom, the optimizer stayed PLAN-ONLY:

1. Did deterministic orientation and reviewed state.
2. Did **not** implement code/config/cron/orchestration changes.
3. Created and claimed a bounded Postgres `agent_tasks` row for the plan-only run.
4. Started a matching `agent_runs` row.
5. Wrote explicit `definition_of_done`, `verification_result`, and `verified_at` on the task.
6. Inserted `loop_metrics` rows including:
   - `tokens_today=280041`
   - `usage_headroom_pct=0`
   - `jobs_skipped_by_budget=1`
   - `gateway_healthy=1`
   - `config_rollbacks=0`
   - `human_approval_pending=0`
7. Appended a compact entry to `wolfy/optimization_todo.md`.
8. Completed task/run as completed because durable plan-only progress was made, with summary explicitly saying implementation was skipped by budget.

## Pitfalls discovered / reinforced

- `strategies.latest_oos_verdict` is a boolean in the current schema. Do not use `coalesce(latest_oos_verdict, '')`; Postgres will raise `invalid input syntax for type boolean: ""`. Use `latest_oos_verdict is not null` or boolean comparisons.
- If a psycopg transaction fails during metric insertion, check whether the transaction rolled back before assuming partial metric/task writes happened. In this run, the failed first insertion wrote zero metrics and left the task/run in progress, so a second corrected insertion was safe.
- In a dirty Hermes repository, do not create a local commit just because a ledger file changed. If the run is budget-gated and the working tree has unrelated profile/curator/runtime diffs, record state in Postgres and the ledger, but avoid committing unless the staged diff is narrowly verified.
- `optimization_todo.md` may already contain non-chronological historical entries from prior patches. Append/prepend the new current run entry narrowly; do not reorganize the whole ledger during a budget-gated pass.

## Final report shape used

```markdown
CHANGED
- PLAN-ONLY run: implementation skipped because budget gate blocked token spend.
- Persisted state: Postgres task `<id>` + run `<id>` completed; added `<n>` `loop_metrics` rows; updated `wolfy/optimization_todo.md`.

VERIFIED
- `budget_gate.py --no-record` -> BUDGET=block ... exit 1.
- `config_guardian.py` -> GUARDIAN=ok ... exit 0.
- `hermes cron list` exit 0; key jobs present.
- Task/run/metrics verification rows present.

KPI/STATE
- `usage_headroom_pct=0`, `jobs_skipped_by_budget=1`, `gateway_healthy=1`, `config_rollbacks=0`.
- `human_approval_pending=0`.
- No code/config/cron orchestration change was made; no local commit created due PLAN-ONLY budget gate and dirty working tree.

BLOCKED/HUMAN ASK
- None.

NEXT ACTION
- When budget headroom recovers, execute one Tier S control-plane slice, preferably OWS-4 Jonah cadence hourly under the self-modification protocol.
```
