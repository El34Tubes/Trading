# Aggressive options-only paper profiles

Use this pattern when a user wants substantially more option opportunities without converting the production-approved underlying strategy into an unreviewed high-risk variant.

## Preserve the baseline

Create a separate, versioned `research_only` strategy instead of mutating the approved strategy or its immutable validation gate. This preserves clean A/B comparison and prevents an aggressive experiment from inheriting production approval.

Required experimental identity:

- `experimental_forward_test=true`
- `strategy_validated=false`
- `experimental_forward_recommendations_allowed=true`
- `instrument_policy=defined_risk_options_only`
- `equity_fallback=false`
- `paper_only=true`
- `no_live_execution=true`
- `broker_order_submitted=false`
- an explicit selector-policy version

Persist these facts on the strategy, signal, option evaluation, and recommendation. Do not assume that an upstream label automatically survives downstream writing.

## Loosen opportunity gates, not evidence gates

Aggressiveness may come from:

- lower relative-volume requirements;
- allowing modest relative underperformance while still requiring positive underlying momentum;
- wider technical invalidation distance;
- treating broad-market trend and sector confirmation as context rather than hard vetoes;
- accepting weaker but still positive breadth;
- allowing high realized volatility;
- a shorter holding horizon;
- permitting a bounded modestly OTM long leg.

Do not loosen:

- exact option-chain and quote provenance;
- timestamp/session alignment;
- rejection of crossed, stale, future, malformed, or nonstandard contracts;
- defined maximum loss and whole-contract sizing;
- maximum-loss paper risk budget;
- daily recommendation cap;
- no-equity-fallback and no-live-execution rules;
- the requirement for positive conservative payoff at the technical target.

Missing volatility structure, breadth, chain data, or an exact selected structure remains fail-closed. "Aggressive" must not mean fabricated prices, lottery-ticket strikes, or illiquid contracts.

## Parameterization discipline

Keep existing strategy behavior unchanged by adding explicit parameters with old behavior as defaults. A separate aggressive profile can override them. Typical parameters include:

- minimum volume ratio and relative-strength excess;
- whether the ticker must outperform the benchmark;
- whether positive absolute return is required;
- maximum stop-risk percentage;
- breadth floor and sector-confirmation requirement;
- holding horizon and target multiple;
- DTE, moneyness, liquidity, quote-width, and conservative-fill bounds.

Store the effective values in every signal/evaluation so results remain auditable. Do not rely only on seed metadata if runtime functions use hard-coded thresholds.

## Writer and selector pitfalls

- Persist the **effective capped risk fraction**, not the caller-requested fraction when the writer clamps it.
- Derive holding-period text from validated strategy metadata; do not leave a legacy hard-coded horizon.
- Strictly validate integer horizons (`type(value) is int`, bounded); reject booleans and coercive fractional values.
- Require the exact expected selector-policy version and complete option legs before experimental authorization.
- Reject a candidate when one indivisible contract exceeds the paper risk budget.
- Apply the daily cap after deterministic ranking and preserve idempotency by strategy, ticker, and signal date.
- Keep default selector policy strict; pass an explicit aggressive policy rather than weakening all option experiments globally.

## Example bounded aggressive profile

A defensible high-opportunity paper profile may use values such as:

- relative volume `>= 0.80`;
- relative-strength excess `>= -0.03` while absolute underlying return remains positive;
- stop distance `<= 10%`;
- breadth `>= 35%` with sector confirmation informational;
- target `1.25R`, maximum hold `7` sessions;
- calls/spreads `7–28 DTE`;
- long strike from 10% ITM through at most 5% OTM;
- open interest `>= 10` **or** volume `>= 1`;
- relative spread `<= 35%`;
- conservative buy fill 80% through the quoted spread;
- maximum 5% paper-equity loss per recommendation and at most three per day.

These are experimental defaults, not universal production thresholds. Version them, test them independently, and revise from forward evidence.

## Verification

Use RED/GREEN tests for:

1. Seed metadata and preservation of the approved baseline.
2. A fixture rejected by the strict strategy but accepted by the aggressive variant.
3. Missing volatility/breadth and excessive stop distance remaining rejected.
4. Modestly OTM positive-payoff selection and farther-OTM rejection.
5. Exact spread, DTE, liquidity, timestamp, and moneyness boundaries.
6. No exact structure, malformed authorization, or oversized one-contract risk producing no recommendation.
7. Effective risk/horizon and complete safety metadata in persisted recommendations.
8. Maximum three recommendations and idempotent reruns.
9. Full-suite, static/no-broker scan, schema idempotency, and before/after production fingerprints against the dedicated test database.
