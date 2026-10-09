# Daily Multi-Setup Evaluator Planning Pattern

Use this reference when Wolfy needs more recommendation opportunities without weakening an approved setup.

## Core diagnosis order

Before adding indicators or relaxing thresholds, measure:

1. intended session versus actual price/feature coverage;
2. scheduled signal universe versus the data-ready/validation universe;
3. pass/fail attrition at every deterministic gate;
4. number of independent setup families;
5. downstream recommendation, option-selection, paper-ledger, and outcome wiring.

A narrow scheduled universe can be the dominant recommendation bottleneck even when broad historical data already exists. Expand opportunity coverage before changing a validated gate.

## Free EOD provider scheduling

When a free provider intentionally defaults to the previous business day, an after-close weekday job may still receive the prior session. Add a next-business-day premarket catch-up:

```text
05:45 ET resolve latest completed exchange session
05:50–06:20 fetch only missing EOD bars/features in bounded shards
06:20 readiness + point-in-time universe snapshot
06:25–06:45 features, regime, strategy evaluations, near misses
06:45–07:00 candidate-only events/options enrichment
07:00 paper recommendation lifecycle and outcomes
07:05 actionable delivery only
```

Use a pinned NYSE calendar or versioned exchange-calendar table; weekend-only date arithmetic is insufficient. Require all benchmark/sector inputs and a declared broad-universe coverage threshold before publication. A partial pipeline is not a clean no-signal run.

## Safe expansion sequence

1. Preserve the approved strategy unchanged with golden parity tests.
2. Build a versioned U.S./liquidity/security-identity universe policy.
3. Shadow caps in stages (for example 100 -> 200 -> 300 -> optional 400).
4. Record one terminal pass/fail evaluation per run/ticker/strategy plus all failed gates.
5. Promote broad production only after coverage, runtime, exclusion, parity, and idempotency checks.
6. Never relax gates to satisfy a recommendation quota.

## Near-miss ledger

Persist deterministic reason codes such as missing data, security ineligible, liquidity, regime, trend, breakout/pullback shape, relative strength, volume, stop risk, extension, breadth, sector, event, option-chain/option-liquidity, correlation, and daily-limit blocks. Aggregate 1/5/20/60-session attrition. Analytics may propose a research hypothesis but must never mutate thresholds automatically.

## Setup portfolio

Prefer orthogonal setup families over threshold clones:

- Keep the governed RS close-confirmed breakout as the production baseline.
- Add a research-only trend pullback/reclaim setup for orderly retracements in established relative-strength trends.
- Complete the research-only volatility contraction/expansion setup, validating underlying behavior separately from option P/L.
- Defer PEAD until actuals, contemporaneous estimates, surprise, publication time, revisions, source, and `available_at` are defensible point-in-time data.
- Deprioritize setup families whose current OOS evidence is weak.

New setups remain `research_only`; passing historical gates permits candidate status at most. Require explicit user approval for paper eligibility and a forward evidence floor before asking.

## Options and allocation

After underlying and portfolio gates reduce the candidate set, fetch exact read-only chains. Deterministically choose a stock-specific `long_call`, `call_debit_spread`, or `no_option`; do not substitute equity for an invalid options structure. Keep underlying outcomes and option outcomes in separate ledgers.

Apply one allocator across strategies: deduplicate ticker, normalize strategy scores, enforce max three/day, existing exposure, aggregate heat, sector concentration, and correlation. Log blocked candidates. Preserve NO TRADE.

## Robust implementation prerequisites

- Isolate development from a dirty operational repository with a clean worktree; never reset/stash user work implicitly.
- Create a dedicated Postgres test database/rollback harness before adding more live-DB integration tests.
- Serialize integration tests, reviews, final revalidation, and live smoke because Wolfy tests may affect shared state.
- Give every daily run an immutable identity containing signal date, decision timestamp, data cutoff, universe policy/version, feature/strategy versions, and source fingerprints.
- Make runs idempotent and fail closed: started -> data incomplete/evaluated -> published, with publication requiring read-back verification.

## User decisions worth surfacing

Ask for judgment where trade-offs materially change behavior:

- free premarket T+1 versus paid same-evening data;
- final broad-universe cap;
- unlevered ETF sleeve policy;
- pullback trigger/target hypothesis before freezing tests;
- sector/correlation concentration;
- paid point-in-time earnings data for PEAD;
- options spread/liquidity strictness;
- forward evidence floor for strategy approval;
- aggregate portfolio heat (three 5% positions imply up to 15%);
- 99% versus 100% broad-universe freshness;
- whether an internal implementation budget cap gets a bounded one-session override.

Operational data catch-up may continue while broad code changes remain budget-gated; never weaken the permanent guardian just to accelerate one session.
