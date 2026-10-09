# Wolfy RS breakout strategy TDD implementation — 2026-07-30

## When to use

Use this reference when implementing Wolfy's first options-focused deterministic recommendation strategy or continuing the recommendation-engine task chain.

## User-approved strategy

Strategy name: `liquid_rs_breakout_continuation`.

Purpose: 1–2 week bullish defined-risk options-oriented setup, evaluated by the underlying stock/ETF technical outcome rather than user fill price or option P/L.

Core deterministic gates:

- EOD-only signal.
- Broad/current Wolfy universe, with data-quality, tradability, manipulation-risk and history gates.
- 5-day high breakout: `close_today > prior_5_day_high` from completed prior bars.
- 20-trading-day relative strength: ticker 20d return > SPY 20d return.
- Volume confirmation: `vol_ratio >= 1.2`.
- Near-high/tightness: close remains within 5% of recent high.
- Trend: close above fast MA and fast MA >= slow MA when available.
- Stop/invalidation: below prior 5-day low.
- Max hold: 10 trading days.
- Profit plan: partial at 1.5R then trail remainder.
- Preferred expression: 2–3 week slightly OTM call spread.
- Options liquidity/OI/volume/spread: informational/user-evaluated only, not a hard paper-recommendation gate.
- No chase if next-session open is >0.5 ATR above trigger.
- Market regime: soft Sentinel gate in v1.

## Implementation pattern used

Follow TDD:

1. Patch `test_eod_signals.py` first.
2. Add a seed test proving `seed_default_strategies()` creates `liquid_rs_breakout_continuation` as `research_only` with setup type `rs_breakout_continuation` and `requires_backtest=true`.
3. Add a deterministic signal test using synthetic ticker bars plus SPY bars. The fixture must create:
   - ticker breakout on the final bar,
   - ticker 20d return > SPY 20d return,
   - final-day volume bump so `vol_ratio >= 1.2`,
   - computed fast/slow MAs and ATR via `compute_and_store_features()`.
4. Verify RED with:
   ```bash
   cd /root/.hermes/wolfy
   python3 -m pytest test_eod_signals.py::test_seed_default_strategies_includes_rs_breakout_as_research_only test_eod_signals.py::test_generate_liquid_rs_breakout_continuation_signal -q
   ```
   Expected failure before implementation: missing strategy row and missing `signals_by_strategy['liquid_rs_breakout_continuation']`.
5. Implement in `eod_signals.py`:
   - add `DEFAULT_STRATEGIES` tuple for `liquid_rs_breakout_continuation`,
   - add `_generate_liquid_rs_breakout(...)`,
   - call it from `generate_eod_signals()`.
6. Verify GREEN:
   ```bash
   python3 -m pytest test_eod_signals.py -q
   python3 -m pytest -q
   ```

## Actual verification result from this slice

- Focused tests after implementation: `2 passed`.
- `test_eod_signals.py -q`: `7 passed`.
- Full Wolfy test suite: `114 passed`.
- Postgres row verified:
  - `strategies.name='liquid_rs_breakout_continuation'`
  - `setup_type='rs_breakout_continuation'`
  - `status='research_only'`
  - params include breakout=5 and RS window=20.
- No setups were created for the new strategy while research-only.

## Agent task state from this slice

Completed:

- `3577` — seed `liquid_rs_breakout_continuation` strategy.
- `3578` — deterministic RS breakout signal generator.

Next queued:

- `3579` — broad-universe recommendation gates.
- `3580` — harden OOS validation gates.
- `3581` — validate `liquid_rs_breakout_continuation`.

## Git checkpoint

Committed and pushed safe source/config/doc/test files only:

```text
d88ac45f9e4a48b4745919ce44d055eb8c01726e
wolfy(rec): seed RS breakout recommendation strategy
```

## Pitfalls to preserve

- Do not interpret user approval to proceed as strategy approval. The strategy remains `research_only` until validation passes and the user explicitly approves it.
- Do not let options liquidity block paper recommendation flow; surface it as a warning/informational field for the user to evaluate manually.
- Do not evaluate success from the user's real option P/L. Evaluate underlying setup accuracy: continuation, MFE/MAE, whether 1.5R was available before invalidation, and 5/10-day outcomes.
- In this repository, many unrelated profile/curator/runtime files may be dirty. Before committing, stage only intended Wolfy source/docs/tests and inspect `git diff --cached --name-status` plus a simple secret scan.
