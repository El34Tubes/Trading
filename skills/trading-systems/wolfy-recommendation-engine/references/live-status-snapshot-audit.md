# Live Wolfy status snapshot audit

Use this when the user asks “where are we at?” or requests a current operational/recommendation status.

## Snapshot sequence

1. Read live clock/date, cron state, budget gate, Postgres task board, and git state. Do not infer current status from memory or the most recent conversational report.
2. Run the deterministic budget probe with `guardian/budget_gate.py --no-record`; a status check must not create accounting rows.
3. Read strategy eligibility from Postgres, including `status`, `metadata.approval_scope`, and `metadata.paper_recommendation_approval`.
4. Audit price and feature coverage by date, not just `MAX(dt)`. Compare the latest date’s symbol count with recent completed sessions.
5. Audit signals with `dt <= current_date`. Live-DB tests may intentionally leave future-dated fixtures, so an unrestricted `MAX(dt)` can falsely report a 2099 signal as current.
6. Separate all-strategy signals from signals belonging to the currently approved paper strategy. Generic/research strategy signals are not recommendation readiness.
7. Read recommendation statuses and open paper trades. Prefer the deterministic summary wrapper when available, but verify its headline against Postgres when coverage is questionable.
8. Inspect scanner run metadata and stored results separately. A completed run may have results even when a compatibility/alias field such as `symbols_scanned` is zero.
9. Treat cron `last_status=ok` as process health, not proof of data completeness. A successful shard can still leave partial latest-session coverage.
10. Report source-control delivery separately: local commits ahead of origin and a dirty tree are operational risks, not market/recommendation results.

## Decision language

- **NO TRADE / cash:** use only when coverage is complete, the strategy is eligible, and no deterministic qualifier passed.
- **No trustworthy fresh recommendation:** use when prices/features/signals are stale or partial, regardless of cron success.
- State paper-only and live-execution-disabled explicitly.
- Lead with the bottom line, then compact bullets for automation, strategy, data freshness, recommendations/trades, budget/task queue, and repository risk.

## Durable SQL pitfalls

Wolfy tables use `prices.dt`, `features.dt`, `signals.dt`, `scanner_runs.run_time`, and `scanner_results`; do not assume names such as `price_date`, `feature_date`, `run_at`, or `scanner_candidates`. When the schema may have evolved, inspect `information_schema.columns` before composing a multi-table status query.