# Aggressive options paper-profile hardening

Use this checklist when adding a higher-frequency or lighter-gate options strategy to a deterministic paper system.

## Preserve the baseline

- Add a separate versioned `research_only` strategy variant; do not silently loosen an approved strategy.
- Keep the strict baseline and aggressive variant available for forward comparison.
- Mark the aggressive path explicitly: `experimental_forward_test=true`, `strategy_validated=false`, `defined_risk_options_only`, `equity_fallback=false`, `paper_only=true`, and `no_live_execution=true`.
- Loosen opportunity gates (RS, volume, breadth, market/sector confirmation, stop width) separately from data-quality and pricing safeguards.

## End-to-end wiring

A seeded strategy and signal generator are not an executable options pipeline. Verify the supported runner can:

1. select the exact strategy/profile;
2. query that strategy's signals;
3. create the correct selector policy;
4. ingest/normalize a timestamped read-only chain;
5. select and persist the structure under the same strategy identity;
6. invoke the recommendation writer with that identity.

Keep the old profile as the backward-compatible default unless rollout explicitly changes it. Reject unknown profiles.

## Quote and numeric validation

- Aggressive policies must require a timezone-aware `decision_time`; `None` must never disable quote-age enforcement.
- Derive `market_date` from `quote_at` in `America/New_York`. If a caller supplies `market_date`, require equality with the derived value; never let it override an old timestamp.
- Require `quote_at <= decision_time` and a bounded quote age.
- Reject booleans before numeric conversion.
- Reject NaN, Infinity, malformed decimals, fractional integer fields, crossed/nonpositive quotes, nonstandard multipliers, stale/future quotes, excessive spreads, and out-of-range moneyness deterministically. Malformed contracts should become rejection reasons, not uncaught exceptions.

## Do not trust selector output at the write boundary

Selector results are caller-controlled data. For an experimental recommendation writer:

- require the normalized/raw contracts, exact policy identity, and a timezone-aware decision timestamp supplied through a trusted writer argument or bound durable evaluation/snapshot row;
- never derive freshness authority solely from the untrusted evaluation document: otherwise a caller can pair an old quote with a forged nearby `decision_time`, obtain an internally consistent recomputation, and bypass the intended age limit;
- independently rerun the canonical selector using the stored signal entry, target, market date, and trusted decision timestamp;
- compare the recomputed selected structure with the submitted structure, including legs, expirations, strikes, conservative fills, target payoff, maximum loss/profit, DTE, and policy facts;
- size only from recomputed maximum loss;
- reject forged, incomplete, stale, or economically inconsistent evaluations.

Presence checks and labels such as `defined_risk=true` are not evidence.

## Portfolio caps and concurrency

A `[:3]` slice enforces only a per-call cap. To enforce a global daily cap:

1. make every writer that can create a cap-consuming paper row take the same transaction-scoped advisory lock keyed by signal date;
2. count existing active paper recommendations for that signal date across recommendation types and strategies;
3. allocate only remaining slots;
4. enforce ticker/date/strategy idempotency with a database unique index and conflict-safe insertion;
5. test repeated calls plus concurrent same-ticker and disjoint-ticker writers;
6. add a mixed-writer race: hold an aggressive insertion uncommitted, start an approved/baseline writer, commit the first transaction, and assert the second writer cannot produce a fourth durable row;
7. report `recommendations_ranked` using remaining global capacity, not the caller's original limit.

Before installing a unique index on populated data, detect duplicates and fail closed rather than deleting or guessing.

## Risk semantics

Distinguish these rules:

- **One indivisible contract exceeds the risk budget:** reject the trade.
- **One-contract maximum:** a separate policy that must not be inferred.

When the policy is total defined loss <= 5% of paper equity, multiple contracts are valid if:

`contracts = floor(risk_budget / recomputed_max_loss_per_contract)`

and `contracts * max_loss_per_contract <= risk_budget`.

Persist effective risk fraction, per-contract maximum loss, quantity, and total maximum loss.

## Verification probes

- A lighter-gate fixture rejected by the strict strategy but accepted by the aggressive variant.
- Missing volatility/breadth still fails closed.
- Modestly OTM eligible; far-OTM rejected.
- Boundary spread and liquidity OR semantics.
- Stale timestamp with spoofed current `market_date` rejected.
- Old quote paired with a forged nearby decision timestamp in the untrusted evaluation rejected because the writer uses an independent trusted decision time.
- Boolean volume and nonfinite/malformed numerics rejected without exceptions.
- Forged selected structure rejected by writer recomputation.
- One contract above budget rejected; multiple contracts within aggregate budget accepted.
- Repeated, same-writer concurrent, and mixed-writer concurrent calls never exceed the global daily cap.
- Full suite, schema idempotency, static/no-broker scan, and before/after production fingerprint.
