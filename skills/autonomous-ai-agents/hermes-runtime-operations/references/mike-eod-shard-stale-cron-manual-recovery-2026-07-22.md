# Mike EOD shard stale-cron recovery — 2026-07-22

## Trigger

Wolfy default-profile cron listed EOD Massive ingest shards 2–5 with prior-day `403 NOT_AUTHORIZED` errors for same-calendar-day Massive/Polygon aggregates, while the live code already defaulted Massive EOD end dates to the previous business day unless `WOLFY_MASSIVE_ALLOW_CURRENT_DAY=1` or `--end-date` is set.

## Safe triage pattern

1. Treat the cron `Last run` traceback as stale evidence until the exact live wrappers are smoked.
2. Run the exact shard wrappers with the interpreter/shebang they use, not `bash`:
   - `python3 /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_1.py`
   - `python3 /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_2.py`
   - `python3 /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_3.py`
   - `python3 /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_4.py`
   - `python3 /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_5.py`
3. Healthy output can be `bars_fetched: 0` when every ticker reports `reason: already_current` at the latest delayed-plan date. That is not a failed ingest.
4. Immediately run deterministic signals after shard recovery:
   - `python3 /root/.hermes/scripts/wolfy_eod_features_signals.py`
5. Verify with real DB facts instead of cron status text:
   - `prices.max(dt)` and per-core-ticker bar counts.
   - `features.max(dt)` and feature rows at latest date.
   - `signals.max(dt)` and signal rows at latest date.
   - recent `runs` rows for `eod_feature_compute` / `eod_signal_generate`.
6. Compile exact invocation layers and run targeted tests:
   - `python3 -m py_compile /root/.hermes/wolfy/eod_price_features.py /root/.hermes/wolfy/orchestration_runner.py /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_*.py /root/.hermes/scripts/wolfy_eod_features_signals.py`
   - `python3 -m pytest /root/.hermes/wolfy/test_eod_price_features.py /root/.hermes/wolfy/test_eod_after_close_ingest_wrapper.py -q`

## Reporting nuance

If direct wrapper smokes pass and Postgres shows current `prices`/`features`/`signals`, report the earlier shard errors as stale cron `Last run` text that should clear on the next scheduled run. Do not change credentials, switch data sources, or claim the Massive key is broken from stale cron output alone.

If the wrappers still request same-calendar-day aggregates and fail with `403 NOT_AUTHORIZED`, the durable fix is to keep the delayed/free-plan default in the live implementation/wrapper before any ticker fetch, preserving explicit opt-in via `WOLFY_MASSIVE_ALLOW_CURRENT_DAY=1` or `--end-date` for paid real-time plans.