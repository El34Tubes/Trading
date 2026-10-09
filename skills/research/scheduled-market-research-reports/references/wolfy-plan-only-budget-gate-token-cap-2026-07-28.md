# Wolfy plan-only optimizer run — token-cap budget block (2026-07-28)

## Trigger

Daily Wolfy optimizer ran at ~02:16 ET. The proactive budget gate blocked implementation:

```text
python3 wolfy/guardian/budget_gate.py --no-record
BUDGET=block token_cap_exceeded tokens_today=302211 cap=200000
exit=1
```

Per the self-optimizing-loop constitution, this means **PLAN-ONLY**: deterministic orientation/review/state updates are allowed; code/config/cron implementation changes are not.

## Verified guardian/cron state

Use cheap guardian and cron checks before recording state:

```text
python3 wolfy/guardian/config_guardian.py --skip-cli
GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;no_probation
exit=0

hermes cron list
exit=0
```

Confirmed no probation marker and optimizer job `92f31b95fccc` remained active. Jonah was still on the OWS-4 backlog cadence (`*/20`) pending a later self-modification run.

## Durable-state pattern used

When budget-blocked but deterministic state writes are allowed:

1. Create or update one plan-only `agent_tasks` row with a stable `source_fingerprint` for the date/run.
2. Mark it `in_progress`, open an `agent_runs` row, record KPI rows, then finish both as `completed` **only if** real verification output exists and no implementation was attempted.
3. Store the verification text in `agent_tasks.verification_result`, set `verified_at`, and later update `commit_hash` if a narrow ledger/docs commit is made.
4. Record KPIs such as `tokens_today`, `usage_headroom_pct`, `jobs_skipped_by_budget`, `gateway_healthy`, `config_rollbacks`, `max_turns`, `parallel_jobs_cap`, `human_approval_pending`, strategy counts, and repo health.

## Psycopg/schema pitfalls reinforced

- Do **not** use `INSERT ... ON CONFLICT (source_fingerprint)` unless a unique/exclusion constraint has been verified. In this environment it failed with `InvalidColumnReference`; use `SELECT id FROM agent_tasks WHERE source_fingerprint=%s`, then `UPDATE` or `INSERT`.
- If a psycopg statement fails inside a transaction, the transaction is aborted. Re-open or roll back before continuing; then verify the task/run/metric rows actually exist.
- `agent_runs` uses `error_message`, not `error`.
- Canonical `loop_metrics` inserts use `metric_key`; compatibility aliases may exist but should not be assumed as the source of truth.

## Commit hygiene

The repo was dirty from unrelated config/profile/skill/autorepair changes. For a plan-only ledger update, stage only the intended file:

```text
git add wolfy/optimization_todo.md
git commit -m "wolfy(opt): record 2026-07-28 plan-only budget block — DoD met (task 3611)" -- wolfy/optimization_todo.md
```

Then persist the resulting unpushed short hash (`e8319dd`) on the task row.

## Report shape

Final cron report stayed compact:

- `CHANGED`: plan-only block, persisted task/run/KPIs, ledger commit.
- `VERIFIED`: budget gate block, guardian ok, cron ok.
- `KPI/STATE`: headroom/token/gateway/strategy/state metrics.
- `BLOCKED/HUMAN ASK`: none unless Tier B is actually waiting.
- `NEXT ACTION`: OWS-4 Jonah cadence reduction when budget headroom recovers.
