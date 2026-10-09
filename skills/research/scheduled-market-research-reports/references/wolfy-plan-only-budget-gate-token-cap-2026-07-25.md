# Wolfy plan-only budget gate token cap — 2026-07-25

Use this as a concrete reference for Wolfy's daily self-optimizing loop when the proactive budget gate blocks implementation but durable state/progress still needs to be recorded.

## Trigger

At Phase 0, run:

```bash
python3 wolfy/guardian/budget_gate.py --no-record
```

Observed result:

```text
BUDGET=block token_cap_exceeded tokens_today=295124 cap=200000
exit=1
```

This means PLAN-ONLY: do deterministic orientation/review/state updates, but do not implement code/config/cron/LLM-job changes.

## Verification commands that mattered

```bash
python3 wolfy/guardian/config_guardian.py
# GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;hermes_cron_list_ok;no_probation

hermes cron list
# optimizer 92f31b95fccc, Jonah, and config guardian present/active

psql "$DSN" -XAtc "select id,status,verification_result from agent_tasks where id=3606; select id,status,records_created from agent_runs where id=349862; select count(*) from loop_metrics where run_id=349862;"
# task completed, run completed, 25 metrics rows

git diff --check -- wolfy/optimization_todo.md
# passed after removing a trailing blank line at EOF
```

## Durable rows/artifacts

- `agent_tasks`: task `3606`, status `completed`.
- `agent_runs`: run `349862`, status `completed`, `records_created=25`.
- `loop_metrics`: 25 KPI rows, including `tokens_today=295124`, `usage_headroom_pct=0`, `jobs_skipped_by_budget=1`, `gateway_healthy=1`, `config_rollbacks=0`, `max_turns=90`, `parallel_jobs_cap=1`, `human_approval_pending=0`.
- Ledger: appended a 2026-07-25 entry to `/root/.hermes/wolfy/optimization_todo.md`.
- Local commit: `f85cb914ae8c` (`wolfy(opt): record plan-only budget block — DoD met (task 3606)`).

## Pitfalls reinforced

- `agent_tasks.source_fingerprint` may not have a unique constraint. Do **not** use `INSERT ... ON CONFLICT (source_fingerprint)` unless the constraint is proven present. Safe pattern: `SELECT id FROM agent_tasks WHERE source_fingerprint=%s`; then `UPDATE` or `INSERT`.
- If a psycopg statement fails during a multi-step state write, the transaction may be aborted/rolled back. Re-open or cleanly retry, then verify task/run/metric rows actually exist.
- Canonical `loop_metrics` columns are `metric_key`, `metric_value`, and `captured_at`; compatibility aliases may exist but should not be assumed for writes.
- `agent_runs` uses `error_message`, not `error`.
- `budget_gate.py` has no `--json`; use plain output and `--no-record` for a no-extra-write gate check.
- `config_guardian.py` has no `--check --json`; use bare `python3 wolfy/guardian/config_guardian.py` for the real health path.
- A narrow local commit of a verified ledger-only update is acceptable during PLAN-ONLY, but inspect staged paths first because the repo is often dirty with unrelated curator/profile/autorepair changes.

## Report shape used

Final cron response stayed compact:

- `CHANGED`: plan-only state/ledger/commit.
- `VERIFIED`: budget gate, guardian, cron list, DB rows, diff check.
- `KPI/STATE`: only notable metrics.
- `BLOCKED/HUMAN ASK`: none if no Tier B ask.
- `NEXT ACTION`: OWS-4 Jonah cadence reduction when headroom recovers.
