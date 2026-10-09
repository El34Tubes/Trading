# Wolfy RS breakout setup-outcome exhaustion — 2026-08-03

Use this as the session-specific reference for options-timed RS breakout validation work.

## User preference captured

The user wants Wolfy to exhaust the current deterministic technical setup before switching strategies, but is open to a better technical strategy if evidence suggests an edge. The user specifically wants backward testing that identifies when a strategy **would have recommended successfully**, where success means the underlying stock/ETF technical setup continued higher and hit deterministic R targets before invalidation, not the user's actual option fill/P&L.

## Implementation/result pattern

1. Keep all new/revised strategies `research_only`; do not create recommendations or paper trades from failed/incomplete validation.
2. First validate broad `liquid_rs_breakout_continuation` and record why it failed:
   - historical research signals generated over available data,
   - OOS Sharpe below user threshold,
   - max drawdown above user threshold.
3. Add a pure setup-outcome evaluator before deeper rule mining:
   - deterministic entry,
   - stop/invalidation,
   - target R multiple,
   - max hold,
   - MFE/MAE,
   - target-before-stop classification.
4. Mine historical success cohorts, but treat them as hypothesis discovery rather than approval.
5. Implement promising revisions as new `research_only` strategy rows, not silent changes to the original.

## Pitfalls fixed

- Tests that touched Postgres used real `SPY`; cleanup deleted benchmark history. Fix cleanup to remove only isolated far-future fixture rows for benchmark tickers and never delete real SPY price/features history.
- Before RS-vs-SPY validation, verify SPY history exists and restore via the normal EOD ingest wrapper if missing.
- For DB tests that touch common symbols/universe rows, use synthetic `ZZ...` tickers and far-future dates, or use `ON CONFLICT`/state restoration for common symbols.

## Research-only variants from this session

### `liquid_rs_breakout_tight_risk_volume`

- Parent: `liquid_rs_breakout_continuation`
- Filters: stop risk <= 4%, RS excess vs SPY >= 2%, `vol_ratio >= 2.0`
- Historical setup outcome: about 58 signals, ~39.7% hit 1.5R, ~31.0% stop rate
- Kept `research_only` because sample/split was too small for promotion.

### `liquid_rs_breakout_close_confirm_1r`

- Parent: `liquid_rs_breakout_continuation`
- Filters: SPY above 50-day SMA, RS excess vs SPY >= 2%, `vol_ratio >= 1.2`, prior-low risk <= 5%
- Stop/invalidation: close back below breakout level
- Target: 1R
- Max hold: 10 trading days
- Historical setup outcome: 1,085 evaluated setups, 63.13% hit 1R, 35.94% stop/invalidation rate, median MFE 1.8539R
- Legacy next-close backtest still failed formal gate (`OOS Sharpe 0.6250 < 0.75`, max DD too high), so do **not** promote under the old gate.

## Next durable build direction

Add a setup-outcome-native validation gate for options-timed strategies. The old next-close backtest is not sufficient for strategies whose management depends on target/stop/time-horizon mechanics. Candidate promotion should require a deterministic, frequency-aware OOS split over setup outcomes, not just next-close return Sharpe.
