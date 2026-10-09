# Wolfy system_metrics + alpha_search_leads alias preservation (2026-07-11)

## Trigger
Mike ops recent-error tails showed ad-hoc/optimizer probes failing on:

- `system_metrics.metric_name` / `metric_value` / `category` / `created_at`
- `alpha_search_leads` view creation/query paths expecting `sqlite_id` while canonical `alpha_leads` had `legacy_id`

These were compatibility drift issues, not market-analysis failures.

## Safe repair pattern
1. Add nullable/read-only compatibility aliases, do not rewrite canonical write paths.
2. Preserve the aliases in both the live initializer and deterministic autorepair:
   - `/root/.hermes/wolfy/postgres_init.sql`
   - canonical `/root/.hermes/scripts/mike_safe_autorepair.py`
   - then run autorepair to sync `/root/.hermes/wolfy/mike_safe_autorepair.py` plus Mike/Clerky profile copies.
3. For `system_metrics`, keep canonical watchdog fields (`captured_at`, `root_used_pct`, etc.) and add aliases:
   - `metric_name TEXT` default/backfill: `storage.snapshot`
   - `metric_value DOUBLE PRECISION` default/backfill: `root_used_pct`
   - `category TEXT` default/backfill: `storage`
   - `created_at TIMESTAMPTZ` default/backfill: `captured_at`
   - trigger: fill aliases before insert/update so future storage-watchdog rows work.
4. For `alpha_search_leads`, expose both names when canonical storage only has `legacy_id`:
   - `legacy_id`
   - `legacy_id AS sqlite_id`

## Verification commands used

```bash
python3 -m py_compile /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py   # second run should be silent
psql -v ON_ERROR_STOP=1 -d wolfy -f /root/.hermes/wolfy/postgres_init.sql
python3 /root/.hermes/scripts/wolfy_storage_watchdog.py
psql -d wolfy -c "select id,metric_name,metric_value,category,created_at from system_metrics order by id desc limit 3;"
psql -d wolfy -c "select id, legacy_id, sqlite_id, ticker, risk_flags from alpha_search_leads limit 3;"
```

Healthy results:
- autorepair second run silent
- `postgres_init.sql` applies with notices only, no error
- `system_metrics` aliases populated for old and new rows
- `alpha_search_leads` query succeeds with both `legacy_id` and `sqlite_id`

## Reporting nuance
If this is the only change during a Mike ops pass, report it as safe schema compatibility preservation and not as a market-system change. It does not alter trading logic, scanner logic, strategy approvals, or recommendation generation.