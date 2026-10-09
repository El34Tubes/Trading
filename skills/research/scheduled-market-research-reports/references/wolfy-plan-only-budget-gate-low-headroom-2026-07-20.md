# Wolfy plan-only budget gate low-headroom run — 2026-07-20

## Trigger

The daily Wolfy optimizer ran under the self-optimizing loop prompt. Phase 0 budget gate returned:

```text
BUDGET=block token_cap_exceeded tokens_today=367522 cap=200000
```

Because the gate blocked implementation, the run had to stay PLAN-ONLY: deterministic orientation/review, no code/config/cron mutation, KPI/state persistence, and a concise final report.

## Durable pattern learned

### Bind the current cron `agent_runs` row instead of creating a duplicate optimizer run

Hermes cron had already opened an `agent_runs` row for the current session:

```text
HERMES_SESSION_ID=cron_92f31b95fccc_20260720_021526
agent_runs.id=330986, job_id=cron:92f31b95fccc, status=started
```

For plan-only optimizer bookkeeping, query by `HERMES_SESSION_ID` and attach the new plan-only `agent_tasks` row to that existing run:

```sql
select id
from agent_runs
where session_id = :HERMES_SESSION_ID
order by started_at desc
limit 1;

update agent_runs
set task_id = :task_id, title = :title
where id = :run_id;
```

Then finish that same row as `completed` with a summary like `Plan-only: budget gate blocked implementation ...`. This avoids producing two overlapping rows for one cron invocation (`analysis` plus separate `optimizer`) and makes the cron session ledger easier to audit.

### Minimal completed-plan-only DoD

A budget-blocked optimizer run can still complete if it made durable, safe progress. Required proof:

- `python wolfy/guardian/budget_gate.py` produced `BUDGET=block ...`.
- `python wolfy/guardian/config_guardian.py` returned `GUARDIAN=ok ... no_probation`.
- `hermes cron list` succeeded and the optimizer job remains enabled.
- No repository/config/cron changes were applied.
- A plan-only `agent_tasks` row was created or updated with a machine-checkable DoD.
- The current cron `agent_runs` row was associated with that task and finished.
- KPI rows were recorded, especially `tokens_today`, `usage_headroom_pct=0`, `jobs_skipped_by_budget=1`, and `gateway_healthy=1`.

Use `blocked` instead of `completed` only when no durable state update or verification happened.

### Psycopg transaction pitfall during orientation

When running several independent Postgres orientation queries in one transaction, one bad query (for example using an old column name such as `notes` instead of `blocker_reason`, or `metric` instead of `metric_key`) aborts the whole transaction and causes later queries to fail with:

```text
current transaction is aborted, commands ignored until end of transaction block
```

For cheap orientation probes, either:

- run each query in its own transaction/connection,
- set autocommit, or
- catch the error and `rollback()` before the next query.

Do not let one schema-alias miss hide later metrics or blockers.

## Final report shape used

```text
CHANGED
- Plan-only run: no code/config/cron changes made because budget gate blocked implementation.
- Recorded optimizer state in Postgres: task <id>, run <id>, <n> KPI rows.

VERIFIED
- budget gate output
- config guardian output
- hermes cron list ok
- Postgres task/run/metrics verification
- Commit: none — no implementation change was allowed under low-headroom PLAN-ONLY mode.

KPI/STATE
- usage_headroom_pct=0
- jobs_skipped_by_budget=1
- gateway_healthy=1
- No probation marker present.

BLOCKED/HUMAN ASK
- None.

NEXT ACTION
- Execute the next queued OWS item when budget recovers.
```
