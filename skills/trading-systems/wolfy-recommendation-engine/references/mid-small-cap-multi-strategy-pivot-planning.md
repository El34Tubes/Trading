# Mid/Small-Cap Multi-Strategy Pivot Planning Pattern

Use this reference when Wolfy pivots from a narrow or large-cap-oriented recommendation flow to a broader stock-only multi-strategy portfolio.

## Reconcile before expanding

Do not rewrite the accepted architecture from scratch. First classify prior tasks as:

- **reuse:** dedicated `wolfy_test`, rollback fixtures, readiness/calendar logic, immutable daily-run ledger;
- **adapt:** approved strategy evaluator, option selector, recommendation writer, outcomes, orchestration, summary;
- **supersede:** policy choices changed by the new approval (universe, portfolio caps, instrument fallback, strategy sleeves);
- **defer:** live execution, broker writes, paid sources, shorts, and strategies still blocked on provenance.

State these explicitly in the plan so implementers do not create parallel engines or accidentally retain contradictory policy.

## Resolve strategy/universe contradictions in the plan

If recommendations are restricted to U.S. common stocks, ETF rotation cannot remain an actionable strategy. Preserve SPY/IWM/MDY as benchmark/regime context and translate the economic hypothesis into weekly industry/sector relative-strength allocation among eligible common stocks. Tests must prove benchmarks and ETFs can supply context but cannot become candidates, recommendations, trades, or outcomes.

## Blocker-first implementation order

When a partially implemented options path exists, close review blockers before broadening its use:

1. One transaction-scoped advisory lock and recount shared by **all** recommendation writers.
2. `decision_at` supplied by the immutable run and independent of `evaluated_at`, fetch time, insert time, and wall-clock time.
3. Reject naive timestamps rather than silently assuming UTC.
4. Strict finite numeric parsing and canonical bounded nonnegative OI/volume; reject booleans, NaN/infinity, negative/overflow values, and malformed containers.
5. Relationally bind run, candidate, ticker, strategy, evaluation, and durable chain snapshot; verify OCC underlying matches ticker.
6. Persist source URL/provider, fetched/market/available timestamps, and payload hash or immutable object reference.
7. Recompute the selected option from the persisted snapshot before recommendation insertion.
8. Install uniqueness through an explicit idempotent migration with populated-data duplicate preflight. Abort and report duplicates; never delete or silently merge them.

## Deliver a thin vertical slice early

After blocker closure, implement the smallest end-to-end useful path before adding new setup families:

```text
readiness -> point-in-time universe -> unchanged approved setup
-> common candidate -> global allocator -> stock fallback in shadow
-> serialized paper writer -> read-back
```

This validates universe, ranking, sizing, concentration, concurrency, idempotency, and paper-only invariants. Keep production publication disabled until exact-chain instrument selection and release gates pass.

## Point-in-time universe contract

Materialize an immutable snapshot before setup evaluation. For each symbol persist both inclusions and exclusions with canonical reasons and a policy fingerprint. Use source-backed type/locale/market/exchange/currency/effective dates and `available_at <= decision_at`; unknown or conflicting identity fails closed.

For a mid/small-cap stock policy, boundary tests must include exact minimum/maximum market cap, price, and liquidity values plus values just outside each bound. Average dollar volume must use the declared number of complete sessions—not a one-day proxy. Explicit ticker replay does not bypass eligibility.

## One allocator and one writer

Every strategy emits the same candidate contract. One global allocator must:

- normalize strategy scores without letting one scale dominate;
- deduplicate ticker while retaining multi-label research evidence;
- account for already-open/recommended positions;
- enforce total slots, per-position risk, aggregate risk, and sector limits;
- preserve zero/fewer recommendations;
- persist selected and blocked decisions with reasons.

Every approved and experimental writer must pass through one serialized writer. Per-writer caps are not a global cap and are race-prone.

## Option-preferred with explicit stock fallback

Treat underlying qualification and instrument expression as separate decisions. Fetch exact read-only chains only for allocated finalists. Prefer a safe bounded-loss long call or call debit spread when snapshot provenance, freshness, liquidity, affordability, and target economics pass. Otherwise retain the valid underlying as `underlying_stock_fallback` with rejection reasons; never fabricate a contract.

Track underlying outcomes for every recommendation. Track option outcomes only when an exact option was selected. Option P&L cannot rewrite underlying strategy governance.

## Aggressive portfolio risk must be measured, not softened silently

When the user explicitly accepts high paper risk, do not insert an unapproved lower heat cap. Chronological portfolio replay must model overlapping positions and current-equity sizing and report:

- risk utilization and blocked capacity;
- terminal equity and maximum drawdown;
- worst day/week and longest loss streak;
- ruin occurrence, date/time to ruin, and no resurrection after ruin;
- historical ruin frequency and block/bootstrap uncertainty;
- results by setup, sector, and regime.

Label model limits. Acceptance of paper ruin risk does not authorize live trading.

## Production-isolation release sequence

Keep tests and populated migration rehearsals in exact database `wolfy_test`. Before production mutation:

1. capture read-only production baselines;
2. test clean bootstrap, populated upgrade, rerun, and concurrent migration;
3. run focused and full suites serially;
4. run multi-session read-only shadow replays;
5. obtain independent spec and code/security review of the exact staged snapshot;
6. secret-scan and confirm production baselines are unchanged.

Then apply reviewed migrations, enable only the already approved strategy first, run a scoped paper-only canary and idempotent rerun, read back all cap/risk/provenance flags, and only then enable one scheduled publisher. Rollback disables the publisher/config; it does not delete audit rows.
