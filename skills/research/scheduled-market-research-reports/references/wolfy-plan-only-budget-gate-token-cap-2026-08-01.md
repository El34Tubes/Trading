# Wolfy plan-only optimizer budget gate — 2026-08-01

## Trigger

The Wolfy daily optimizer ran as a cron job at ~02:15 ET with the self-optimizing-loop prompt. The proactive budget gate blocked implementation:

```text
python wolfy/guardian/budget_gate.py --no-record
BUDGET=block token_cap_exceeded tokens_today=204507 cap=200000
exit=1
```

Per the optimizer rules, this required PLAN-ONLY: deterministic review/state/KPI updates only; no code/config/cron/orchestration implementation.

## Verified health checks

Use the current CLI/script surface, not invented flags:

```text
python wolfy/guardian/config_guardian.py --skip-cli
GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;no_probation
exit=0

hermes cron list
exit=0
optimizer job active: 92f31b95fccc, schedule 15 2 * * *
```

`config_guardian.py` does not expose `--health-json`; use bare invocation, `--skip-cli`, or import `health(...)` when structured checks are needed.

## State update pattern

When budget blocks implementation but orientation/verification/state writes succeed, create/complete a small plan-only `agent_tasks` row and matching `agent_runs` row, then record loop metrics. In this run:

- `agent_tasks.id=3654`, status `completed`, title `2026-08-01 daily optimizer plan-only budget block`.
- `agent_runs.id=374954`, status `completed`, `records_created=11`.
- KPI rows recorded: `jobs_skipped_by_budget=1`, `tokens_today=204507`, `usage_headroom_pct=0`, `gateway_healthy=1`, `config_rollbacks=0`, `max_turns=90`, `parallel_jobs_cap=1`, `human_approval_pending=0`, `iteration_success_rate≈0.99415`, `regressions_introduced=0`.

Use `agent_runs.error_message`, not `error`; canonical loop metrics columns are `metric_key`/`metric_value`. If a psycopg orientation query fails, isolate/reopen the transaction before continuing because later statements in the same transaction will be aborted.

## Report shape

Final cron response should stay compact:

- `CHANGED`: no implementation; state/task/KPI updates only.
- `VERIFIED`: budget block, guardian OK, cron OK, DB rows verified.
- `KPI/STATE`: only notable numbers.
- `BLOCKED/HUMAN ASK`: none unless Tier B is actually waiting.
- `NEXT ACTION`: when headroom recovers, one Tier S slice only (preferred OWS-4 Jonah cadence hourly, or remaining OWS-1 wake-gate coverage).

Do not commit when no verified implementation change occurred. A ledger-only commit is acceptable only if it is intentionally staged narrowly and verified.