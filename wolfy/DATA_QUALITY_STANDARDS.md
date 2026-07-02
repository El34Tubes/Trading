# Wolfy Data Quality Standards

Scope: all EOD price/volume, corporate-action, and event data feeding features, signals, backtests,
tickets, and reports. Postgres is the only live store. Direction ratchet: thresholds may only tighten
without human review.

## Completeness
- MUST: tier-1/2 tickers fresh within 2 trading days (blocker beyond); lower tiers within 5.
- MUST: depth-ready = ≥495 daily bars before a ticker is eligible for signals/backtests.
- MUST: earnings coverage known for a ticker before any setup implies event safety; unknown coverage
  is stated as earnings_unknown (fail-closed), never implied-clear.

## Correctness
- MUST: single adjustment basis per ticker. Any corporate action triggers full-history re-fetch and
  replace; an unresolved split audit older than one ingest cycle is a blocker.
- MUST: bar integrity on insert — high ≥ max(open,close), low ≤ min(open,close), prices > 0,
  volume ≥ 0, unique (ticker, date). Violations are recorded quality events, never silently skipped;
  skipped/None bars are counted and reported per run.
- SHOULD: |1-day close move| > 40% without a matching corporate action is flagged for review.

## Consistency
- SHOULD: weekly cross-source close reconciliation on a sample of tier-1/2 names; mismatch > 25bps is
  a review event; persistent mismatch is a blocker.
- MUST: every backtest is stamped with universe_asof and survivorship_bias status; removed tickers'
  history is never deleted.

## Timeliness & Provenance
- MUST: every bar row carries its source; the ledger reports ingest_source_mix and fallback activations.
- MUST: ledger freshness/coverage/quality metrics are recomputed after every ingest and are the sole
  basis for "data is ready" claims. No LLM may assert data readiness not shown by the ledger.

## Statistical integrity (validation layer)
- MUST: survives_oos requires both the Sharpe threshold and minimum trade counts (OOS ≥ 20, IS ≥ 60).
- MUST: number of trials per strategy family is recorded; promotion thresholds deflate with trials.
- MUST: costs and all gate thresholds may only tighten autonomously; loosening requires human review.
