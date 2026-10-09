# Options backtesting versus forward paper testing

## Decision rule

Use historical backtesting to validate the underlying directional setup. Use forward paper testing to validate the exact option expression and operational realism. Neither predicts the future; each removes a different class of uncertainty.

| Question | Historical underlying backtest | Forward options paper test |
|---|---:|---:|
| Did target beat invalidation? | Yes | Yes, forward only |
| Does the setup survive chronological OOS? | Yes | Not until sample accumulates |
| Was an exact contract available? | No without historical chains | Yes |
| Was the bid/ask realistically tradable? | No without quote history | Yes |
| Did IV crush hurt the trade? | No without IV history | Yes |
| Did the selector choose a good structure? | No | Yes |

## When an approval gate may be bypassed

For paper-only research, a user may choose to let an unvalidated strategy emit experimental recommendations before its historical gate passes. This is acceptable only when:

- no live order is possible;
- the output is explicitly labeled experimental and unvalidated;
- deterministic setup facts are persisted;
- option-chain and pricing safeguards remain hard requirements;
- the experimental stream is kept distinct from approved production recommendations.

Skipping validation must not be represented as proving the strategy. It accelerates evidence collection; it does not manufacture evidence.

## Minimum underlying-thesis record

- strategy and transformation version
- signal and decision timestamps
- entry baseline, invalidation, target, and horizon
- target-before-stop outcome
- MFE/MAE in R and percent
- realized-volatility and contraction/expansion facts
- market regime, breadth, and sector context
- publication/availability timestamps for external inputs

## Minimum option-expression record

- OCC identifiers or complete leg identity
- underlying, expiration, strikes, rights, and quantities
- chain snapshot timestamp and source
- each leg's bid, ask, midpoint, last, volume, and open interest
- IV and Greeks only when directly supplied
- conservative assumed entry and exit fills
- spread debit/credit, width, breakeven, maximum loss/profit
- contract count and sizing basis
- daily or exit marks with quote timestamps
- fees, slippage, realized P&L, IV change, and exit reason

## Fill discipline

Do not score a paper strategy using optimistic midpoint fills by default. Keep at least:

1. midpoint mark for comparability;
2. conservative executable estimate, such as buying nearer ask and selling nearer bid;
3. explicit stale/wide/crossed-quote rejection.

If liquidity evidence is missing, classify the option expression as unavailable rather than assuming a fill.

## Two-ledger attribution

Grade the setup and option independently:

- `setup_good/option_good`: signal and expression both worked.
- `setup_good/option_bad`: investigate premium, expiration, strike, IV, spread, or fill selection.
- `setup_bad/option_good`: likely volatility luck or structure effects; do not credit the directional edge blindly.
- `setup_bad/option_bad`: both thesis and expression failed.

This attribution is the main reason to paper-test options even after an underlying backtest exists.

## Practical sample sequence

- Start experimental recommendations immediately if paper-only research is the goal.
- Review operational failures from the first 5–10 observations.
- Compare structures after roughly 20–30 legitimate setups.
- Seek stronger conclusions after 50–100 observations and multiple volatility regimes.
- Keep historical underlying validation running in parallel; do not wait for the forward sample to test price-derived features that can be evaluated honestly now.
