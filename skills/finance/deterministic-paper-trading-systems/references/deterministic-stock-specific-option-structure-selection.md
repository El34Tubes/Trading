# Deterministic stock-specific option-structure selection

Use this pattern when the user wants each qualifying stock setup to receive the option expression that best fits that stock, rather than forcing one structure across all symbols.

## Bounded first version

Keep the initial selector aligned with the existing directional thesis:

- bullish underlying signals only;
- compare `long_call`, `call_debit_spread`, and `no_tradable_option_structure`;
- permit a bounded DTE window such as 7–35 calendar days;
- defer credit spreads, condors, calendars, butterflies, bearish structures, and portfolio optimization until separately justified and tested.

This is stock-specific without becoming an unbounded strategy generator.

## Deterministic pipeline

For every qualifying signal:

1. Read the underlying entry, invalidation, technical target, signal timestamp, and holding horizon.
2. Obtain one timestamped, read-only chain snapshot.
3. Normalize contracts and preserve the original payload.
4. Reject contracts before candidate generation when they have missing/crossed quotes, future/stale timestamps, nonstandard multipliers, excessive relative spreads, or inadequate volume/open interest.
5. Generate long-call candidates and same-expiration call debit spreads.
6. Use conservative quote-side fills rather than assuming midpoint execution.
7. Calculate debit, maximum loss, maximum profit where bounded, breakeven, and payoff at the underlying technical target.
8. Rank candidates deterministically with stable tie breakers.
9. Select one structure or explicitly return no option recommendation.
10. Persist the chain, all candidates, rejection reasons, selected structure, policy version, and safety metadata.

## Practical scoring guardrails

- Do not let target-state percentage return choose a far-OTM lottery ticket merely because leverage looks large. Without trustworthy delta/probability inputs, constrain the long leg to ATM or modestly ITM.
- A requested test expectation is not automatically economically correct. If the test expects an inferior strike, compare capital at risk and target-state payoff; correct the test rather than distorting the selector.
- Favor a target-aligned debit spread when selling the higher strike materially offsets expensive premium and the technical target is near the short strike.
- Favor a long call when premium is reasonable and capping credible upside would reduce the conservative target-state result.
- Never force a selection when every candidate fails pricing or liquidity checks.

## Forward-test gate policy

Historical validation of the underlying setup and forward validation of the option expression are separate. If the user explicitly authorizes unvalidated experimental paper recommendations:

- allow the named research strategy into the forward paper stream without changing its status to approved;
- retain `experimental_forward_test=true`, `strategy_validated=false`, `paper_only=true`, `no_live_execution=true`, `broker_order_submitted=false`, and `equity_fallback=false`;
- continue requiring an exact selected structure, defined risk where applicable, trustworthy quotes, and maximum-loss-based paper sizing;
- keep the option-pricing safeguards because removing them makes the experiment meaningless.

## Audit schema pattern

Use an additive Postgres table keyed idempotently by `(ticker, signal_dt, strategy_name)` with:

- underlying entry and target;
- chain source and fetch timestamp;
- full normalized chain JSON;
- complete evaluation JSON;
- selected structure;
- explicit paper/no-live safety booleans;
- created/updated timestamps.

A rerun may update the same evaluation row but must not create duplicate recommendations.

## Integration boundary

Keep chain acquisition separate from selection. The selector should accept normalized JSON regardless of whether the source is Robinhood MCP, another read-only provider, or a fixture. If broker OAuth is disabled, do not silently enable it or claim live-chain automation is complete. Provide a JSON adapter for exercising the pipeline, and report authentication as the remaining integration step.

## Verification

- Follow RED–GREEN–REFACTOR for selector, ledger, writer, and pipeline slices.
- Test long-call selection, spread selection, no-trade behavior, DTE bounds, stale/future quotes, idempotent persistence, experimental-gate metadata, maximum-loss sizing, and missing-chain behavior.
- Run focused tests, full regression, compilation, migration twice with `ON_ERROR_STOP`, relevant diff checks, staged secret scan, no-live-order symbol scan, and a clean-export regression.
- In dirty repositories, stage only the intended paths and inspect `git diff --cached --name-status` before committing.
