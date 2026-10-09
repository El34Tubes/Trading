# Adversarial release audits for options paper writers

Use these probes when reviewing a bounded option selector plus a paper-recommendation writer. Green happy-path tests are insufficient because the integration boundary often accepts caller-supplied evaluation JSON.

## 1. Treat selector output as untrusted

A writer must not authorize a recommendation merely because an evaluation claims:

- `status=selected`;
- the expected policy version;
- `defined_risk=true`;
- paper/no-live safety labels;
- a positive `target_profit` and `max_loss_per_contract`.

Recompute or independently validate the economic and provenance contract before persistence:

- ticker and decision/signal timestamp binding;
- expiration and DTE derived from dates rather than trusted scalar DTE;
- positive finite strikes, bids, asks, debit, target payoff, and maximum loss;
- bid <= ask;
- standard multiplier and exact leg count;
- long/short expiration equality and long strike < short strike for debit spreads;
- policy moneyness bounds;
- maximum loss arithmetic from conservative fills and multiplier;
- selected candidate membership in the persisted evaluated-candidate set;
- source snapshot identity or durable evaluation-row identity.

Adversarial probe: handcraft a mapping with the right labels but a decades-old quote, negative strike/quotes, fabricated low maximum loss, and positive target profit. The writer must block it without raising and create no row.

## 2. Quote provenance and freshness

Do not make freshness optional in a paper selector. A current-looking `market_date` supplied beside an old `quote_at` is not proof of freshness.

- Require a finite, timezone-aware quote timestamp.
- Bind it to an explicit decision timestamp and enforce maximum age.
- Derive New York market date from the raw UTC timestamp in trusted normalization code; do not trust arbitrary caller-provided `market_date` as an override.
- Preserve raw UTC timestamp, derived market date, delayed status, and source snapshot provenance.
- Missing decision time, timestamp, or provenance must yield `no_tradable_option_structure`, not disable the age gate.

Probe both a next-day UTC after-close timestamp that correctly maps to the prior U.S. session and an old timestamp paired with a spoofed current market date.

## 3. Canonical numeric and boolean validation

Reject malformed feed values before arithmetic:

- booleans are not valid integers (`type(value) is int`, not `int(value)`);
- integer counts/multipliers must be canonical bounded integers;
- decimals must parse successfully, be finite, and satisfy explicit bounds;
- reject `NaN`, positive/negative infinity, fractional integer strings, negative liquidity, and malformed quote fields.

Return deterministic rejection reasons instead of allowing `ValueError` or `decimal.InvalidOperation` to abort the whole batch. Probe `volume=true`, `open_interest="10.5"`, `multiplier="100.0"`, and `bid="NaN"`.

## 4. Position-size invariants

If a strategy contract says one contract maximum, implement that invariant independently of percentage-risk sizing. `floor(risk_budget / max_loss)` alone can produce multiple contracts.

Probe a risk budget larger than twice a cheap contract's maximum loss and require exactly one contract. Also verify that one indivisible contract above budget is rejected rather than rounded up.

## 5. Cumulative daily caps and atomic idempotency

A per-call slice such as `eligible[:3]` is not a daily cap. Before insertion, count already-processed recommendations in all relevant states for the same strategy/date and consume only the remaining capacity.

Probe:

1. one call creates three candidates;
2. a second call with disjoint tickers on the same date creates zero;
3. existing `paper_candidate` and `paper_logged` rows both consume capacity;
4. concurrent writers cannot exceed the cap.

A `SELECT`-then-`INSERT` existence check is not concurrent idempotency. Enforce an authoritative database uniqueness key such as `(ticker, signal_dt, strategy_name)` using normalized scalar columns or a supported generated/indexed representation, then use conflict-safe insertion. Serialize the daily-cap decision with an advisory/row lock or an equivalent transactional design. Probe two synchronized writers and require one durable row and at most the configured daily total.

## 6. Malformed-container, binding, and domain-boundary probes

Field-level fuzzing is not enough. Probe malformed contract containers (`None`, booleans, scalars, strings, lists, and empty mappings) because code may catch subscription/parsing errors and then raise while building the rejection record with `contract.get(...)`. The selector and writer should return a deterministic rejection without an uncaught exception.

Require timestamps to be timezone-aware at both policy and quote boundaries. Never repair a naive quote timestamp by silently attaching UTC; reject it. Include a positive after-close probe where next-day UTC maps to the prior New York market date.

Canonical integer syntax is only half the validation contract. Enforce explicit domain bounds: liquidity counts must be nonnegative and reasonably bounded. In an `open_interest >= minimum OR volume >= minimum` gate, a negative value in one field must not be excused because the other passes. Probe negative and oversized values independently for both fields.

Bind evaluations to the recommendation ticker and source provenance, not merely to recomputed economics. A dangerous implementation can recompute a valid structure from contracts belonging to ticker `OTHER` and persist it under ticker `TARGET` because the selected structure does not contain the evaluation ticker. Probe cross-ticker substitution and require a durable evaluation/snapshot identity or independently validated underlying identity.

Also fuzz source-signal and sizing inputs that feed recomputation (`close`, invalidation, target multiple, ranking fields, account equity, risk fraction, and limits). Invalid, boolean, nonfinite, or malformed values must fail closed per row rather than aborting the batch.

## 7. Safe review execution

Run adversarial writes only against the exact dedicated test database and wrap them in rollback. Capture a database-enforced read-only production checksum before and after focused and full suites. Freeze the reviewed Git commit and require the worktree to remain clean. A transient integration-test deadlock that disappears on isolated retry and a clean full rerun is evidence to report, not a durable product finding; preserve the retry pattern rather than encoding the transient failure.

For concurrency claims, supplement ordinary tests with synchronized multi-connection probes: launch disjoint same-date writers behind a barrier and verify the durable total never exceeds the cap, then launch two same-key writers and require one durable row. Sequential idempotency tests do not prove either property.

Verify schema guarantees through every ownership path. A uniqueness index created only by a runtime `ensure_*_schema()` call may be absent before first use and can make a nominal dry run execute DDL. Require a forward migration and canonical initialization definition as well as the runtime mirror; query the production catalog read-only during review to report deployment state without changing it.
