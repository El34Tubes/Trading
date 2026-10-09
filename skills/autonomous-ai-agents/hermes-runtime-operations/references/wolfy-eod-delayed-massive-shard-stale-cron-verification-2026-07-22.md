# Wolfy EOD delayed Massive shard verification after stale cron 403s (2026-07-22)

## Trigger

Use this when Wolfy default-profile EOD ingest shards show recent `Massive API HTTP 403 ... plan doesn't include this data timeframe` / `NOT_AUTHORIZED` for same-calendar-day `/v2/aggs/.../<today>/<today>` requests, but the code may already have been patched to default Massive EOD to the previous business day.

## Pattern

1. Treat cron `Last run ... error` as historical status until the exact wrapper is smoked. Do not report the shards as still broken from cron text alone.
2. Confirm the code path defaults to the previous business day unless `WOLFY_MASSIVE_ALLOW_CURRENT_DAY=1` or `--end-date` is supplied.
3. Run the exact shard wrappers, not a guessed script path:
   ```bash
   for f in /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_{1,2,3,4,5}.py; do
     echo "## $f"
     python3 "$f" || exit $?
   done
   ```
4. Healthy output may have `bars_fetched: 0` with every ticker `skipped: true` and `reason: already_current`. That is OK when Postgres already has the previous business day's bars.
5. After shard verification, run the deterministic signal wrapper so prices/features/signals share the same latest date:
   ```bash
   python3 /root/.hermes/scripts/wolfy_eod_features_signals.py
   ```
6. Verify Postgres freshness directly:
   ```sql
   select max(dt) as prices_max_dt,
          count(distinct ticker) filter (where dt=(select max(dt) from prices)) as tickers_at_max
   from prices;
   select max(dt) as features_max_dt,
          count(distinct ticker) filter (where dt=(select max(dt) from features)) as tickers_at_max
   from features;
   select max(dt) as signals_max_dt,
          count(*) filter (where dt=(select max(dt) from signals)) as signals_at_max
   from signals;
   ```
7. If direct smokes pass but `hermes --profile default cron list --all` still shows yesterday's failed `Last run` for shards 2-5, classify it as stale cron status text until the next scheduled run records success.

## Reporting

Report concrete facts: which wrappers exited 0, the latest `prices`/`features`/`signals` dates/counts, whether `signals_upserted` ran, and that no setup creation is expected if strategies are non-approved. Keep the data-plan note precise: Wolfy is intentionally one-business-day delayed on the current Massive plan unless the user upgrades/enables current-day access.
