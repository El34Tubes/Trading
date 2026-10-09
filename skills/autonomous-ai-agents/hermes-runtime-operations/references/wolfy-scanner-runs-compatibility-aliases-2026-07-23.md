# Wolfy scanner_runs compatibility aliases (2026-07-23)

## Trigger

Mike ops cron log showed an ad-hoc/read-only Postgres probe failing with:

```text
ERROR: column "finished_at" does not exist
select id, started_at, finished_at, status, symbols_scanned, ... from scanner_runs
```

The live `scanner_runs` table used canonical fields such as `run_time`, `completed_at`, `data_source`, and `scanner_results` child rows, while the probe expected common run-ledger aliases.

## Safe repair pattern

Use non-destructive compatibility aliases on `scanner_runs`; do **not** rename canonical columns or rewrite scanner persistence.

Aliases added/backfilled:

- `scanner_runs.finished_at TIMESTAMPTZ` mirrored from `completed_at` / `run_time`.
- `scanner_runs.status TEXT` defaulted to `completed` for completed historical rows.
- `scanner_runs.symbols_scanned INTEGER` derived from `count(scanner_results where run_id=scanner_runs.id)`, else `0`.
- Preserve existing aliases `started_at`, `completed_at`, and `mode`.

Preserve the repair in all live layers:

1. `/root/.hermes/wolfy/postgres_init.sql`
2. `/root/.hermes/wolfy/wolfy_postgres_pipeline.py` table initializer for fresh DBs
3. canonical `/root/.hermes/scripts/mike_safe_autorepair.py`
4. run autorepair to sync `/root/.hermes/wolfy/mike_safe_autorepair.py` plus Mike/Clerky profile copies

## Verification

Run:

```bash
python3 -m py_compile \
  /root/.hermes/scripts/mike_safe_autorepair.py \
  /root/.hermes/wolfy/mike_safe_autorepair.py \
  /root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py \
  /root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py \
  /root/.hermes/wolfy/wolfy_postgres_pipeline.py

psql -v ON_ERROR_STOP=1 -d wolfy -f /root/.hermes/wolfy/postgres_init.sql
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py  # second run should be silent

psql -d wolfy -c "
select id, started_at, finished_at, status, symbols_scanned, mode
from scanner_runs
order by id desc
limit 3;
select
  count(*) filter (where finished_at is null) as missing_finished_at,
  count(*) filter (where status is null) as missing_status,
  count(*) filter (where symbols_scanned is null) as missing_symbols_scanned
from scanner_runs;
"

python3 /root/.hermes/wolfy/wolfy_intraday_scanner_snapshot.py --max-symbols 1 --min-ranked 0
```

Expected:

- SQL init succeeds with `ON_ERROR_STOP=1`.
- Exact failing query returns rows.
- Missing alias counts are all zero.
- Autorepair second run is silent.
- Intraday scanner smoke exits 0 silently.

## Pitfall

When patching large SQL/autorepair files with repeated function names, ensure the scanner-run trigger is inserted as its own top-level function, not accidentally nested inside `wolfy_sync_agent_runs_aliases()`. Re-read the patched region and run `psql -v ON_ERROR_STOP=1` immediately.