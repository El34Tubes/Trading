# Wolfy Massive history bootstrap vs daily incremental EOD ingest — 2026-07-02

Session lesson: when auditing Wolfy's Massive/Postgres OHLCV history load, distinguish the one-time historical bootstrap from the recurring daily EOD ingest. The user explicitly does not want daily pipelines repeatedly pulling two years of history.

## Durable facts / pattern

- Initial two-calendar-year Massive OHLCV load is a **bootstrap/backfill** task only.
- Normal daily EOD ingest should fetch only the current/missing days once a ticker has enough stored history.
- In the current code path, `eod_price_features.py` may receive `--days 730`, but `_fetch_incremental_massive_bars()` uses that full window only for missing/underfilled tickers; otherwise it starts at `latest_dt + 1` or skips as `already_current`.
- Practical Massive free-tier readiness threshold remains `DEPTH_READY_BARS` / `min_history_bars=495` because two-calendar-year pulls can return ~499 bars depending on the trading calendar.
- Full-history refetches remain allowed for deliberate repair cases such as split/corporate-action adjustment-basis repair; do not treat those as normal daily ingest.

## Audit/update checklist

1. Query Postgres coverage from `prices`/`features` and `universe_backfill_targets`; report bootstrap completion separately from daily freshness.
2. Check the bounded tiered backfill cron/job separately from daily EOD shards.
3. If the user asks whether a TODO exists, search/update both the visible planning ledger and Postgres `agent_tasks`.
4. Ensure the TODO/DoD says the bounded backfill should be run-until-complete / auto-disable / no-op after all active targets reach readiness.
5. Verify daily ingest with an incremental-regression test such as `test_incremental_massive_plan_skips_current_ticker_without_api_call` before claiming daily runs are protected.

## Wording to use

Say: "The 2-year load is bootstrap-only; daily EOD should be incremental/current-day only after readiness, except deliberate repair refetches."

Avoid implying that passing `--days 730` means the daily job reloads two years every day; inspect the fetch plan first.