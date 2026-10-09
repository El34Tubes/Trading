# Wolfy Massive EOD shard catch-up and signal recompute (2026-07-22)

## Trigger

Default-profile Wolfy EOD ingest shards showed `Massive API HTTP 403` / `NOT_AUTHORIZED` for same-calendar-day `/v2/aggs/ticker/.../<today>/<today>` requests after close. This matched the delayed/free-plan access pattern rather than a broken API key.

## Durable lesson

When the same-day default has already been patched to use the previous business day, cron `Last run` may still show the prior shard failures until the next scheduled tick. Do not report the pipeline as still broken from stale cron text alone. Prove the live path with the exact wrappers and catch up deterministic state when safe.

## Safe catch-up workflow

1. Confirm wrappers/code compile:
   ```bash
   python3 -m py_compile \
     /root/.hermes/wolfy/eod_price_features.py \
     /root/.hermes/wolfy/orchestration_runner.py \
     /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_{1,2,3,4,5}.py \
     /root/.hermes/scripts/wolfy_eod_features_signals.py
   ```
2. Run targeted tests:
   ```bash
   cd /root/.hermes/wolfy && python3 -m pytest test_eod_price_features.py -q
   ```
3. Smoke Massive no-write path:
   ```bash
   cd /root/.hermes && python3 /root/.hermes/scripts/wolfy_eod_after_close_ingest.py --dry-run --tickers SPY --source massive --days 10
   ```
4. If the delayed bar is now accessible, manually catch up all shards:
   ```bash
   cd /root/.hermes
   for n in 1 2 3 4 5; do
     python3 /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_${n}.py || exit $?
   done
   ```
5. Recompute deterministic signals/setups after the price/features catch-up:
   ```bash
   python3 /root/.hermes/scripts/wolfy_eod_features_signals.py
   python3 /root/.hermes/scripts/wolfy_eod_features_signals.py --dry-run
   ```
6. Verify facts from Postgres, not stale cron `Last run` text:
   ```sql
   -- Core universe should share one latest price date and adequate bars.
   WITH core(ticker) AS (VALUES
     ('SPY'),('QQQ'),('IWM'),('DIA'),('XLK'),('XLF'),('XLY'),('XLI'),('XLE'),
     ('XLV'),('XLP'),('XLU'),('XLB'),('XLRE'),('XLC'),('AAPL'),('MSFT'),('NVDA'),
     ('AMZN'),('GOOGL'),('META'),('TSLA'),('AVGO'),('JPM'),('LLY'),('V'),('UNH'),
     ('COST'),('NFLX'),('AMD'),('ORCL'),('CRM'),('PANW'),('SMH'))
   SELECT count(*) AS core_count, min(p.latest_dt), max(p.latest_dt), min(p.bars), max(p.bars)
   FROM core c
   JOIN LATERAL (SELECT max(dt) latest_dt, count(*) bars FROM prices WHERE ticker=c.ticker) p ON true;

   SELECT max(dt) AS latest_signal_dt,
          count(*) FILTER (WHERE dt=(SELECT max(dt) FROM signals)) AS signals_at_latest
   FROM signals;
   ```

## Reporting nuance

- If manual shard catch-up and signal recompute succeed, report that cron will retain the old shard error text until the next scheduled run updates `Last run`.
- Treat `0` approved-gated setups as healthy when non-approved strategies are correctly blocked/watch-only.
- Do not change credentials or upgrade API plans; this is a delayed-data access behavior unless fresh smokes still fail after the delay window.
