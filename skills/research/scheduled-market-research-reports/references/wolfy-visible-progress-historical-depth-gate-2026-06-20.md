# Wolfy visible progress ledger historical-depth gate (2026-06-20)

Session pattern for the daily Wolfy optimization planner.

## Context

The daily optimizer needed a safe, bounded improvement while frequent Wolfy cron jobs were near due. Broad strategy/backtest edits and task-board mutation were deferred. The selected low-risk change was to make the visible progress ledger more useful for EOD strategy validation readiness.

## Durable technique

Add a read-only historical-depth section to deterministic progress/status helpers such as `visible_progress_ledger.py`:

- Query `prices` grouped by ticker for `min(dt)`, `max(dt)`, and `count(*)`.
- Report aggregate depth facts: ticker count, earliest first date, latest last date, min bars, median bars, tickers above/below the project threshold.
- Keep it read-only: no DB writes, no strategy promotion, no setup creation, no trading action.
- Surface the depth row in Markdown tables alongside price/feature freshness, scanner freshness, signals, setups, positions, cron status, and strategy gates.
- Keep `candidate is not approved` visible for all non-approved strategies.

Example aggregate query shape:

```sql
WITH per_ticker AS (
  SELECT ticker, min(dt) AS first_dt, max(dt) AS last_dt, count(*)::int AS bar_count
  FROM prices
  GROUP BY ticker
)
SELECT count(*)::int AS tickers_with_prices,
       min(first_dt)::text AS earliest_first_dt,
       max(last_dt)::text AS latest_last_dt,
       min(bar_count)::int AS min_bars,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY bar_count)::int AS median_bars,
       count(*) FILTER (WHERE bar_count >= 500)::int AS tickers_ge_500_bars,
       count(*) FILTER (WHERE bar_count < 500)::int AS tickers_lt_500_bars
FROM per_ticker;
```

Threshold note: use a business-day bar threshold that matches the actual EOD data calendar. In this session the DB had a two-calendar-year span but 502 trading bars; `>=500` was a better practical threshold than `>=504`, which would have falsely shown every ticker as shallow.

## Verification pattern

- Compile the helper: `python3 -m py_compile /root/.hermes/wolfy/visible_progress_ledger.py`.
- Run JSON dry run and Markdown dry run.
- Confirm the output includes the historical-depth row and does not imply any actionable/approved setup.

Avoid piping tool/script output directly into an interpreter just to truncate it, e.g. `python script.py | python3 -c ...`; Tirith may block this as pipe-to-interpreter. Prefer full output, temp files, shell-safe tools, or direct script flags for compact output.