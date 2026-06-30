# Wolfy visible ledger tiered data-load status — 2026-06-27

Use this pattern when the daily Wolfy optimizer needs to improve visibility without running market-data pulls, backtests, schema migrations, or task-state mutations during frequent cron windows.

## Trigger

- Trend/OOS validation is blocked by uncertain universe coverage.
- Tiered backfill helpers exist or are in progress, but the user needs a concise visible status of what is actually loaded.
- Cron/process conflict check allows only read-only helper changes.

## Safe implementation shape

Patch `/root/.hermes/wolfy/visible_progress_ledger.py` only. Keep it read-only.

Add a `data_load_status` collection that joins Postgres `universe` to per-ticker `prices` coverage:

```sql
WITH per_ticker AS (
    SELECT ticker, max(dt) AS latest_dt, count(*)::int AS bar_count
    FROM prices
    GROUP BY ticker
), universe_rows AS (
    SELECT symbol,
           coalesce(nullif(wolfy_tier, ''), nullif(tier, ''), 'unassigned') AS tier,
           coalesce(active, true) AS active,
           coalesce(enabled, true) AS enabled,
           coalesce(backfill_enabled, true) AS backfill_enabled
    FROM universe
)
SELECT tier,
       count(*)::int AS universe_tickers,
       count(*) FILTER (WHERE active AND enabled)::int AS active_enabled_tickers,
       count(p.ticker)::int AS tickers_with_prices,
       count(*) FILTER (WHERE p.bar_count >= 500)::int AS tickers_ge_500_bars,
       count(*) FILTER (WHERE active AND enabled AND p.ticker IS NULL)::int AS active_enabled_missing_prices,
       count(*) FILTER (WHERE active AND enabled AND backfill_enabled AND (p.ticker IS NULL OR p.bar_count < 500))::int AS backfill_attention_tickers,
       min(p.bar_count)::int AS min_bars,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY p.bar_count)::int AS median_bars,
       max(p.latest_dt)::text AS latest_price_dt
FROM universe_rows u
LEFT JOIN per_ticker p ON p.ticker = u.symbol
GROUP BY tier
ORDER BY min(CASE tier
    WHEN 'blue_chip' THEN 1
    WHEN 'etf_core' THEN 2
    WHEN 'large_cap' THEN 3
    WHEN 'mid_cap' THEN 4
    WHEN 'small_cap' THEN 5
    ELSE 99 END), tier;
```

Render as a Markdown section after the snapshot:

`Tier | Universe | Active+Enabled | With Prices | >=500 Bars | Missing Prices | Backfill Attention | Median/Min Bars | Latest Price`

## Expected reading

A healthy first-stage EOD universe usually has `blue_chip` and `etf_core` mostly loaded. If `large_cap`, `mid_cap`, or `small_cap` show high `backfill_attention_tickers`, defer broad OOS validation and make the next build target a bounded tiered EOD price backfill.

## Safety boundaries

- No DB writes.
- No cron edits.
- No strategy approval or setup creation.
- No broker access, live trading, or money movement.
- Do not run long backfills or walk-forward jobs in the daily optimizer if frequent operations/report jobs are near.

## Verification

Run:

```bash
python3 -m py_compile /root/.hermes/wolfy/visible_progress_ledger.py
python3 /root/.hermes/wolfy/visible_progress_ledger.py --limit 0
python3 -m pytest /root/.hermes/wolfy/test_visible_progress_ledger.py -q
git diff --check -- /root/.hermes/wolfy/visible_progress_ledger.py /root/.hermes/wolfy/optimization_todo.md
```

The visible ledger should continue to state: closing-data only, deterministic gates, no auto-execution, human approval required, and `candidate is not approved` for non-approved strategies.
