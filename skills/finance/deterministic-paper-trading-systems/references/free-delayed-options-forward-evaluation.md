# Free delayed options for forward paper evaluation

Use this pattern when historical contract-level data is unavailable and the goal is to forward-test exact option pricing without broker credentials.

## Bounded role

A public delayed chain is suitable for after-close paper research, not live execution. It should be fetched only after the underlying deterministic strategy qualifies a ticker. Do not scan the entire stock universe for chains.

## Minimum normalized contract

Persist:

- OCC symbol, underlying, option type, expiration, strike, multiplier, standard-contract flag
- bid, ask, bid/ask size, volume, open interest
- IV and Greeks when genuinely available
- raw source timestamp, New York market date, delayed flag, source URL
- last trade time when supplied

Keep the original raw payload or complete normalized snapshot in the audit ledger.

## Cboe public delayed-feed pattern

A verified public shape was:

`https://cdn.cboe.com/api/global/delayed_quotes/options/{TICKER}.json`

The payload includes a top-level timestamp, underlying quote fields, and `data.options[]` with contract quote/liquidity/analytics fields. Treat this as an operationally useful public feed with no contractual SLA; add a live smoke that checks status, schema keys, contract count, and usable positive-bid/ask contracts.

## Point-in-time pitfall

Cboe's snapshot timestamp is UTC. An after-close U.S. snapshot can have the next UTC calendar date. Preserve:

- `quote_at`: original timezone-aware UTC timestamp
- `market_date`: `quote_at` converted to `America/New_York`, then `.date()`

Use `market_date` for EOD signal-date matching and UTC `quote_at` for freshness/decision-time checks. Do not reject a valid August 12 after-close snapshot merely because UTC says August 13.

## Analytics placeholder pitfall

Some deep contracts carry `iv=0` and zero Greeks when analytics are unavailable. Do not interpret these as measured zero implied volatility. Normalize IV/Greeks to unavailable unless the source provides a positive IV and meaningful analytics.

## Deterministic selector boundary

For a first bullish version:

- allowed outcomes: long call, same-expiration call debit spread, or no option recommendation
- expiration window: bounded, e.g. 7–35 calendar DTE
- long leg: ATM or modestly ITM when reliable delta is unavailable
- hard rejects: missing/zero/crossed quotes, excessive relative spread, stale/future quote, insufficient OI and volume, nonstandard multiplier, nonpositive target-state payoff
- conservative fills: penalize both bought and sold legs relative to midpoint
- sizing: maximum contractual loss; reject if one indivisible contract exceeds risk budget

Record all candidates and rejection reasons, not only the winner.

## Experimental gate policy

If the user explicitly wants forward research before historical option validation, retain:

- `experimental_forward_test=true`
- `strategy_validated=false`
- `historical_approval_gate_overridden_for_paper_research=true`
- `paper_only=true`
- `no_live_execution=true`
- `broker_order_submitted=false`
- `equity_fallback=false`

The approval bypass applies only to experimental paper recommendations. It does not permit fabricated prices, weak liquidity, oversized contracts, or live execution.

## Verification checklist

1. Unit-test OCC parsing, decimal strikes, calls/puts, timestamps, zero-IV placeholders.
2. Unit-test bounded ticker deduplication and that chains are fetched only for qualifying signals.
3. Run a live single-ticker source smoke and report total contracts, positive bid/ask contracts, and analytics coverage.
4. Run a source-to-selector smoke with a hypothetical target but no recommendation write.
5. Run the production-date CLI in dry-run mode; zero qualifying signals should result in zero chain fetches.
6. Run full tests, compilation, diff checks, secret scan, live-order-symbol scan, and clean-export regression.
