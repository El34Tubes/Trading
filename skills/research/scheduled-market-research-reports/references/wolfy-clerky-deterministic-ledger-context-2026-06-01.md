# Wolfy/Clerky deterministic ledger context (2026-06-01)

## Problem

The four-hour Clerky administrative ledger spent tokens rediscovering SQLite/Postgres schemas and issued fragile ad-hoc SQL against the Kanban DB, causing errors like:

```text
sqlite3.OperationalError: no such column: e.event_type
sqlite3.OperationalError: no such column: e
```

The underlying issue was not corrupted data. It was an LLM-driven status job guessing column names in a production ledger context.

## Durable pattern

For recurring administrative/status jobs, prefer a deterministic pre-run context script that:

1. Prints a concise factual header with generation time and prior-ledger cutoff.
2. Reads cron status from `hermes --profile default cron list --all` when production jobs live in the default profile.
3. Queries known schemas directly and prints compact TSV/line-oriented sections.
4. Includes recent events, open tasks, SQLite counts, Postgres coordination counts, usage/quota state, and recent cron sessions.
5. Tells the LLM to use the script output as the factual source and not rediscover schemas unless investigating an anomaly.

This preserves the useful Clerky narrative summary while avoiding schema-probing failures and reducing token waste.

## Implementation notes from the fix

- Added global helper: `/root/.hermes/scripts/wolfy_clerky_activity_context.py`.
- Synced profile wrapper: `/root/.hermes/profiles/clerky/scripts/wolfy_clerky_activity_context.py`.
- Wired cron job `a739dac0d264` (`Clerky four-hour Wolfy activity report`) to use `script: wolfy_clerky_activity_context.py`.
- Updated Mike safe autorepair so the Clerky wrapper remains synchronized.
- Verified with:
  - `python3 /root/.hermes/scripts/wolfy_clerky_activity_context.py`
  - `hermes --profile default cron list --all`
  - Postgres guard and Wolfy smoke tests.

## SQL/schema pitfalls

- Kanban board DB: `/root/.hermes/kanban/boards/wolfy/kanban.db`.
- Kanban `task_events` columns observed: `id`, `task_id`, `run_id`, `kind`, `payload`, `created_at`; use `kind`, not `event_type`.
- Hermes state DB `sessions` primary key is `id`, not `session_id`; token columns include `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens`, `tool_call_count`.
- Postgres `agent_runs.started_at` is `timestamp with time zone`; compare with `to_timestamp(<epoch>)`, not raw integer comparisons.

## Reporting rule

If the deterministic context script succeeds, Clerky should summarize facts from it. If it fails, report the helper failure as an infrastructure issue and avoid inventing ledger activity.
