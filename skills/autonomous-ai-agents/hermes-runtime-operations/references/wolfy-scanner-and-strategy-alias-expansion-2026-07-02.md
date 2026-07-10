# Wolfy scanner/strategy alias expansion (2026-07-02)

## Trigger
Mike ops saw recurring Jonah/Wolfy ad-hoc Postgres probes fail on drifted read-only column expectations:

- `scanner_results.metadata`
- `scanner_results.trend_50_200`
- `scanner_results.pattern`
- `scanner_results.rs_spy_20d`
- `scanner_results.rs_qqq_20d`
- `strategy_rules.universe_tags`

The canonical live data already existed under current columns (`scanner_results.notes`, `trend_regime`, `gap_reversal_flag`, `rs_spy_20`, `rs_qqq_20`, and `strategy_rules.topic_tags`).

## Safe repair pattern
Use non-destructive compatibility aliases rather than changing canonical write paths:

```sql
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS metadata JSONB;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS trend_50_200 TEXT;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS pattern TEXT;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS rs_spy_20d DOUBLE PRECISION;
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS rs_qqq_20d DOUBLE PRECISION;
```

Backfill mirrors:

- `metadata = COALESCE(metadata, notes, '{}'::jsonb)`
- `trend_50_200 = COALESCE(trend_50_200, trend_regime, notes->>'trend_50_200', notes->>'trend_regime')`
- `pattern = COALESCE(pattern, gap_reversal_flag, notes->>'pattern', notes->>'gap_reversal_flag')`
- `rs_spy_20d = COALESCE(rs_spy_20d, rs_spy_20, notes numeric fallback)`
- `rs_qqq_20d = COALESCE(rs_qqq_20d, rs_qqq_20, notes numeric fallback)`

Preserve in the scanner alias trigger so future inserts/updates stay compatible.

For `strategy_rules`, update the compatibility view to include:

- `universe_tags = topic_tags` equivalent for both live `strategies` rows and archived `knowledge_chunks(source_table='sqlite.strategy_rules')` rows.

## Files to preserve
Patch both durability layers:

- `/root/.hermes/wolfy/postgres_init.sql`
- canonical `/root/.hermes/scripts/mike_safe_autorepair.py`

Then run the canonical autorepair script so it syncs:

- `/root/.hermes/wolfy/mike_safe_autorepair.py`
- `/root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py`
- `/root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py`

## Verification
Run real probes and health checks:

```bash
python -m py_compile /root/.hermes/scripts/mike_safe_autorepair.py \
  /root/.hermes/wolfy/mike_safe_autorepair.py \
  /root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py \
  /root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py
python /root/.hermes/scripts/mike_safe_autorepair.py
python /root/.hermes/scripts/mike_safe_autorepair.py  # second run should be silent
psql -d wolfy -v ON_ERROR_STOP=1 -f /root/.hermes/wolfy/postgres_init.sql
```

If a concrete failing ad-hoc probe exists, rerun it exactly. In this session:

- `/root/.hermes/wolfy/tmp_query_panw_3179.py` passed after the aliases were added.
- `/root/.hermes/wolfy/tmp_query_cnc_3181.py` remained passing.

Also verify ledger health:

```sql
select count(*) filter (where metadata is not null) metadata_rows,
       count(*) filter (where trend_50_200 is not null) trend_alias_rows,
       count(*) filter (where pattern is not null) pattern_rows,
       count(*) filter (where rs_spy_20d is not null) rs_spy_alias_rows,
       count(*) filter (where rs_qqq_20d is not null) rs_qqq_alias_rows
from scanner_results;

select column_name,data_type
from information_schema.columns
where table_name in ('scanner_results','strategy_rules')
  and column_name in ('metadata','trend_50_200','pattern','rs_spy_20d','rs_qqq_20d','universe_tags')
order by table_name,column_name;
```

## Pitfalls
- Do not rewrite Jonah queries as the durable fix if probes keep drifting; preserve safe aliases centrally.
- Do not convert `strategy_rules` from a compatibility view into a mutable duplicate table.
- If cron list shows just-due no-agent jobs while a Mike LLM ops cron is active and the tick lock was recently touched, treat it as an active-run artifact until the active run exits; verify direct script smokes rather than declaring the scheduler stuck immediately.
