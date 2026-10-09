# Wolfy intraday scanner bounded Postgres snapshot (2026-07-10)

## Trigger
Default-profile no-agent cron `Wolfy script-only intraday scanner snapshots` timed out after 120s when the scanner attempted the full expanded universe. Direct manual runs showed the wrapper could hang far past cron timeout. The live path was also calling `wolfy_scanner.run_scan(..., db_path=None, persist=True)`, but `run_scan` only persisted when `persist and db_path`, so Postgres scanner rows were not guaranteed on live no-SQLite cron paths.

## Safe repair pattern
1. Keep live Wolfy scanner cron Postgres-only; do not reintroduce retired `wolfy.db` as the operational source of truth.
2. Add a bounded, deterministic rotating subset to the no-agent snapshot helper:
   - default `--max-symbols 32` for cron safety;
   - `--max-symbols <= 0` keeps full-universe manual behavior;
   - rotate by day/hour so repeated snapshots cover the universe over time instead of pinning the first N tickers.
3. Make `wolfy_scanner.run_scan(..., db_path=None, persist=True)` call `persist_scan(ranked, None, universe)` so live Postgres persistence still happens when no SQLite compatibility path is supplied.
4. Preserve tests/legacy smokes with an explicit optional `--db-path` compatibility path; SQLite in tests is acceptable, live cron fallback is not.
5. Keep successful no-agent runs silent; only print compact threshold alerts.

## Verification commands used
```bash
python3 -m py_compile \
  /root/.hermes/wolfy/intraday_scanner_snapshot.py \
  /root/.hermes/wolfy/wolfy_scanner.py \
  /root/.hermes/scripts/wolfy_intraday_scanner_snapshot.py

python3 /root/.hermes/scripts/wolfy_intraday_scanner_snapshot.py --universe ticker-list --ticker-list SPY,QQQ,AAPL,MSFT --max-symbols 4 --min-ranked 0 --max-failure-rate 1.0
python3 /root/.hermes/scripts/wolfy_intraday_scanner_snapshot.py --min-ranked 0 --max-failure-rate 1.0
python3 /root/.hermes/scripts/wolfy_intraday_scanner_snapshot.py

python3 -m pytest \
  /root/.hermes/wolfy/test_intraday_scanner_snapshot.py \
  /root/.hermes/wolfy/test_wolfy_scanner_alpha_handoffs.py \
  -q -o 'addopts='

psql -d wolfy -c "select id, universe, run_time, (select count(*) from scanner_results sr where sr.run_id=scanner_runs.id) results, (select max(data_date) from scanner_results sr where sr.run_id=scanner_runs.id) latest_dt from scanner_runs order by id desc limit 3;"
```

## Reporting nuance
If `hermes --profile default cron list --all` still shows the old timeout immediately after the fix, direct smoke + fresh Postgres rows prove the repair. Manually triggering `hermes --profile default cron run <job_id>` may only set a just-due timestamp until the active LLM cron tick clears; do not declare scheduler failure from that stale `Last run` alone.