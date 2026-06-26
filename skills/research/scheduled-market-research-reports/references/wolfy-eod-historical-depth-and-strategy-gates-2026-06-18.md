# Wolfy EOD historical-depth and strategy-gate lesson — 2026-06-18

## Trigger

The user asked where progress was because visible Wolfy output did not make clear that backend work was continuing. The session then moved into concrete EOD framework work: historical data depth, signal backfill, walk-forward validation, and gate-aware reporting.

## Durable lesson

For Wolfy/Hermes-EOD, do not treat a strategy backtest as meaningful until the underlying daily OHLCV depth is verified. Shallow windows can produce misleading validation and user-visible stagnation because strategy gates remain empty or underpowered.

## Pattern to reuse

1. **Verify EOD ingest depth before strategy work.**
   - Inspect per-ticker daily bar counts and date range in Postgres.
   - If bars are shallow (for example ~60–90 calendar days), fix the ingest wrapper to request a longer default history before tuning strategy logic.
   - For swing/EOD validation, prefer at least ~730 calendar days where the data source allows it.

2. **Protect the ingest default with a regression test.**
   - Add a small wrapper test that asserts live/default ingest requests at least the intended historical depth.
   - Use RED → GREEN: first show the test fails with the shallow default, then patch the wrapper and rerun.

3. **Backfill deterministic features/signals after extending history.**
   - Recompute prices/features/signals across the expanded range before drawing conclusions.
   - Report row counts and date ranges plainly: prices, features, signal dates, and strategy signal counts.

4. **Keep the human approval gate strict.**
   - Walk-forward OOS validation may promote a strategy to `candidate`, but `candidate` is not actionable.
   - Only human-approved strategies may drive capital/paper setup proposals under the Hermes-EOD rule.
   - Failed strategies remain `research_only` and blocked from setup generation.

5. **When a strategy fails, run targeted diagnostic variants before changing production rules.**
   - Compare simple filters such as volume confirmation thresholds and volatility regimes.
   - For the trend-volume-vol-regime test, early evidence suggested high-volume spike/chase regimes can hurt signal quality while normal-volume confirmation may be cleaner.
   - Treat this as a hypothesis requiring TDD and walk-forward validation, not as a production rule by itself.

6. **Respond to “not seeing progress” with concrete artifacts, not reassurance.**
   - Summarize exact completed backend work, test output, DB counts, gate status, and the next implementation target.
   - Include pending items that still block visible trade setups.

## Example status shape

```text
Historical depth: 34 tickers, 502 bars each, 2024-06-18 → 2026-06-18
Tests: 8 passed
Signals backfilled: 450 dates
Strategy states:
- PEAD: research_only, no trades
- Trend-volume-vol-regime: research_only, failed OOS
- Sector momentum: candidate, still not human-approved
Next: test normal-volume-confirmation variant under TDD before production change
```

## Pitfalls

- Do not claim “progress” just because cron jobs ran; show durable artifacts or measurable state changes.
- Do not let a `candidate` strategy leak into actionable recommendations.
- Do not tune rules against a shallow historical slice and then present the result as robust.
- Do not bury gate failures in prose; put them in a compact table and state the blocker directly.
