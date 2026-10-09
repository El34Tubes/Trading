# Wolfy Massive same-day EOD 403 on delayed/free plan — 2026-07-21

## Symptom

After the market close, Wolfy EOD ingest shards 2/5 through 5/5 failed with Massive/Polygon daily aggregate requests like:

```text
RuntimeError: Massive API HTTP 403 for /v2/aggs/ticker/UNH/range/1/day/2026-07-21/2026-07-21:
{"status":"NOT_AUTHORIZED","message":"Your plan doesn't include this data timeframe. Please upgrade your plan at https://polygon.io/pricing"}
```

Shard 1 was already OK because those symbols were current enough; later shards tried to fetch the same calendar day.

## Durable fix pattern

Treat this as delayed-data plan behavior, not a broken credential. Do not fake credentials or force same-day EOD access.

Patch the cron-facing Massive EOD path so the default aggregate `end_dt` is the previous business day unless an operator explicitly opts into same-day access:

- add `_previous_business_day(day)` helper;
- add `_default_massive_eod_end_dt(today=None)` returning previous business day by default;
- allow override with `WOLFY_MASSIVE_ALLOW_CURRENT_DAY=1` or explicit `--end-date YYYY-MM-DD`;
- pass `end_dt` through `_fetch_incremental_massive_bars()` / `massive_ingest()`;
- make dry-run orchestration use the same helper.

This lets daily cron run safely one business day delayed on free/delayed plans while preserving an opt-in path for paid real-time plans.

## Verification commands

Use the exact cron wrappers rather than only unit tests:

```bash
python3 -m py_compile \
  /root/.hermes/wolfy/eod_price_features.py \
  /root/.hermes/wolfy/orchestration_runner.py \
  /root/.hermes/wolfy/orchestration_config.py \
  /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_1.py \
  /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_2.py \
  /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_3.py \
  /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_4.py \
  /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_5.py
cd /root/.hermes/wolfy && python3 -m pytest test_eod_price_features.py -q
python3 /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_1.py
python3 /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_2.py
python3 /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_3.py
python3 /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_4.py
python3 /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_5.py
psql -d wolfy -c "select max(dt) as latest_price_dt, count(*) filter (where dt=(select max(dt) from prices)) as rows_on_latest from prices; select ticker, max(dt) latest_dt, count(*) bars from prices where ticker in ('SPY','QQQ','IWM','AMZN','UNH','ORCL') group by ticker order by ticker;"
```

If a wrapper-specific test file exists in the current tree, run it too; otherwise do not fail the ops pass just because historical notes mention `test_eod_after_close_ingest_wrapper.py`. The exact wrapper smoke is the authoritative verification for cron-facing behavior.

Healthy delayed-plan smoke output may have `bars_fetched: 0` with every fetch-plan item `skipped: true`, reason `already_current`, and `latest_dt` equal to the prior business day. That is OK; it avoids a same-day API request that the plan rejects.

## Reporting nuance

Cron `Last run` may continue to show the earlier shard errors until the next scheduled run. If the exact wrappers now exit 0 and Postgres has current prior-business-day bars, report the fix as verified and note that cron status will age out on the next scheduled shard window.
