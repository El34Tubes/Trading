# Wolfy split-safe EOD ingest and verified closure

Use this pattern when incremental adjusted-price ingestion can mix pre/post-split adjustment bases.

## Deterministic implementation pattern

1. Read each ticker's `min(dt)`, `max(dt)`, and bar count from Postgres.
2. Query split actions from the earliest stored date through the EOD ingest cutoff. If the shared corporate-action helper also retrieves dividends, provide a split-only option so this planning check does not pay for unrelated pages.
3. Key split resolution by `(ticker, execution_date)`, not merely ticker. For every unresolved split inside that ticker's stored window, force `start_dt=full_start_dt` and emit `reason=corporate_action_refetch` in the deterministic fetch plan.
4. Upsert the full adjusted history so existing dates are replaced on the provider's current adjustment basis.
5. Only after the refetch returns bars and the upsert succeeds, insert a Postgres completion marker such as `price_data_quality_events.reason='corporate_action_refetch_completed'` with the covered split execution dates in JSON detail. Keep marker and data writes in the same transaction.
6. During validation, suppress `recent_split_requires_adjustment_audit` only for exact split keys with a completion marker. A failed/zero-bar refetch must remain unresolved.

## Required idempotency proof

Use a synthetic ticker fixture with both an old earliest bar and a bar at the current ingest cutoff:

- First plan: full-history fetch, `reason=corporate_action_refetch`, exact `full_start_dt`, adjusted fetch enabled.
- Persist a completion marker for the split date.
- Second plan: `already_current`, no aggregate-bar API call, zero fetched/new rows.
- Validation: zero unresolved split audits for that exact completed split.
- Cleanup: assert zero synthetic price, event, and run rows remain after the test.

Run the targeted ingest test first, then the full Wolfy suite. This catches accidental repeated multi-year downloads and unresolved-audit churn.

## Dirty live-repository closure

- Respect the two-file throttle by keeping logic and tests to the canonical module/test pair when possible.
- Stage only intended paths and assert the staged path list before committing; unrelated live config/profile/runtime changes are common.
- Run a staged forbidden-pattern scan to prove no broker execution, auto-execution, money movement, or strategy-approval path was introduced.
- After commit, obtain the authoritative hash with `git rev-parse HEAD`. Never infer or fabricate the remaining characters from a short hash. Store that exact hash in `agent_tasks` verification metadata, then read the row back.
- Record KPIs before completing the task/run, and verify the distinct KPI count against the run ID.
- If a broad backlog task is closed as a bounded slice, immediately create explicit dependent follow-up tasks for every deferred requirement so completion does not hide remaining work.