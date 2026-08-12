# Wolfy Options Paper-Structure Support Proposal

Date: 2026-08-11
Task: 3236 — Options paper-structure support
Status: Recommendation/proposal only; no implementation and no live execution.

## Recommendation

Proceed with **advisory options paper-structure metadata**, but keep the canonical paper trade as the underlying equity/ETF setup until option-chain data is connected and validated.

In short:

- Wolfy should continue to generate deterministic recommendations from underlying stock/ETF signals.
- Paper accounting should keep the equity fallback row as the canonical `paper_trades` record.
- Options should be attached as advisory metadata: preferred structure, expiration window, candidate strikes, bid/ask sanity, open interest/volume, IV, and defined-risk spread shape.
- Do not calculate Greeks or option fair value from an LLM.
- Do not hard-block an otherwise valid equity setup solely because options metadata is missing.
- Do not route Robinhood orders or live trades.

## Why this is the right next step

The approved strategy, `liquid_rs_breakout_close_confirm_1r`, is validated as an underlying technical setup:

- deterministic EOD signal;
- 1R target;
- close-back-below-breakout invalidation;
- max hold 10 trading days;
- setup-success validation based on the underlying ticker, not user option fill/P&L.

Options are useful for the user's preferred expression — 2–3 week slightly OTM call spreads — but the strategy edge has been validated on the underlying move. Until option-chain data is ingested and sanity-checked, options should enrich the ticket without becoming the source of truth.

## Minimum required data before option structures can be more than advisory

For each recommended ticker and signal date/session:

1. Underlying price context
   - EOD close baseline;
   - stop/invalidation price;
   - 1R target;
   - expected hold window.

2. Option chain
   - expirations;
   - strikes;
   - call/put side;
   - bid, ask, mark/mid;
   - volume;
   - open interest;
   - implied volatility;
   - greeks if supplied by broker/data source, never LLM-invented.

3. Spread construction
   - long call strike near/slightly OTM;
   - short call strike near target or next liquid strike above;
   - expiration 2–3 weeks out, configurable;
   - debit/mid estimate;
   - max loss;
   - max gain;
   - reward/risk;
   - bid/ask spread sanity.

4. Liquidity sanity checks
   - non-zero bid and ask on both legs;
   - spread width not extreme versus mid;
   - reasonable open interest/volume;
   - no stale quote timestamp where available.

## Proposed deterministic metadata shape

Store under `recommendations.notes.option_spread` or future `paper_trades.notes.option_spread_advisory`:

```json
{
  "advisory_only": true,
  "structure": "defined_risk_call_debit_spread",
  "expiration_window": "2-3_weeks",
  "underlying_entry": "40.03",
  "underlying_stop": "39.73",
  "underlying_target": "40.33",
  "long_leg": {
    "right": "call",
    "strike_selection": "slightly_otm_or_nearest_liquid_above_entry",
    "bid": null,
    "ask": null,
    "open_interest": null,
    "volume": null,
    "iv": null,
    "delta": null
  },
  "short_leg": {
    "right": "call",
    "strike_selection": "nearest_liquid_at_or_above_underlying_target",
    "bid": null,
    "ask": null,
    "open_interest": null,
    "volume": null,
    "iv": null,
    "delta": null
  },
  "liquidity_status": "missing_chain_data",
  "hard_gate": false,
  "user_evaluates_liquidity_manually": true
}
```

## Safety rules

- Paper-only.
- No live execution.
- No broker order placement.
- No money movement.
- No LLM-generated Greeks, prices, spreads, or implied volatility.
- Missing options data means `liquidity_status=missing_chain_data`, not a fabricated contract.
- If Robinhood MCP is connected, start read-only and use it only for chain/tradability/account-position enrichment.

## Implementation recommendation

Defer full option-spread paper P/L until after three foundations are done:

1. Read-only broker/options chain adapter.
2. Deterministic spread selector with tests and stale/liquidity guards.
3. Separate option-paper ledger fields/tables that do not overwrite the underlying setup-success record.

The next build slice should be read-only enrichment only:

- function: `build_option_spread_advisory(underlying_setup, option_chain)`;
- input: deterministic recommendation metadata plus externally sourced option chain;
- output: advisory JSON only;
- tests: missing chain, illiquid legs, valid chain, stale chain;
- no live orders.

## Decision

**Proceed, but advisory-only for now.**

This supports the user's preferred trade expression while keeping the validated strategy and paper performance ledger grounded in the underlying stock/ETF technical setup.
