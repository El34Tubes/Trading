# Wolfy Paper Recommendation Engine Session Notes — 2026-08

## Durable architecture learned

A safe paper-recommendation engine was built in vertical slices:

1. Deterministic approved-strategy recommendation writer.
2. Postgres paper-trade logger.
3. Visible recommendation-engine ledger section.
4. Underlying setup-success outcome review.
5. Paper-ledger learning metrics.
6. Daily script-only summary.

## Approval gate details

Do not rely on `strategies.status='approved'` alone. A live smoke revealed unrelated strategies can be left in approved-like states by tests or old workflows. The durable predicate for the Wolfy paper-only flow became:

- `strategies.status='approved'`
- `metadata.approval_scope='paper_only_no_live_execution'`
- `metadata.paper_recommendation_approval=true`

The writer and logger both need the full predicate.

## Idempotency details

- Recommendation writer must treat both `paper_candidate` and `paper_logged` as existing rows when checking duplicates.
- Paper logger should be idempotent by `recommendation_id` and return `skipped_existing` on repeat runs.
- Outcome reviewer should skip if `recommendation_outcomes.paper_trade_id` already exists.

## Scoping details

Avoid global scans where a workflow is meant to act on a specific EOD cycle. Support explicit:

- `signal_dt`
- `tickers`
- recommendation/trade IDs where useful

Tests should include unrelated rows or live-existing state so unscoped code fails during RED.

## Outcome grading

Paper trade review grades the underlying setup, not option fills:

- target/stop/time-stop classification;
- MFE/MAE in R/percent;
- `recommendation_outcomes` row;
- paper trade close fields;
- notes include `setup_success_metric=underlying_stock_technical_setup_not_option_fill_pnl`.

## Learning metrics

Useful columns added non-destructively to `paper_trades`:

- `max_adverse_excursion`
- `exit_efficiency`
- `stop_distance_atr`

Exit efficiency is realized R divided by MFE R. A target hit can have efficiency less than 1.0 if the underlying moved beyond target intraday before the modeled exit.

## Options stance

Options are advisory until deterministic option-chain ingestion exists. Missing chain data is a fact to store, not a gap to fill with invented contracts, Greeks, IV, bids/asks, or option P/L.

## Summary delivery pattern

For routine status, prefer script-only cron (`no_agent=true`) that prints a deterministic read-only summary. This avoids recurring LLM spend and prevents summary jobs from making decisions.
