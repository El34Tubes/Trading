# Wolfy scanner_results.pattern_flags compatibility alias — 2026-07-02

## Context
A Mike ops run saw repeated Jonah ad-hoc Postgres probes against `scanner_results` drift from canonical scanner fields to common top-level aliases. Most aliases already existed (`metadata`, `volume`, `trend_50_200`, `pattern`, `rs_spy_20d`, `rs_qqq_20d`), but a fresh probe failed on `pattern_flags`.

## Safe repair pattern
Use the existing non-destructive alias approach rather than changing canonical scanner writes:

```sql
ALTER TABLE scanner_results ADD COLUMN IF NOT EXISTS pattern_flags JSONB;

UPDATE scanner_results
SET pattern_flags = COALESCE(
  pattern_flags,
  notes->'pattern_flags',
  jsonb_strip_nulls(jsonb_build_object(
    'pattern', COALESCE(pattern, gap_reversal_flag, notes->>'pattern', notes->>'gap_reversal_flag'),
    'gap_reversal_flag', gap_reversal_flag,
    'squeeze_flag', squeeze_flag,
    'trend_regime', trend_regime
  ))
)
WHERE pattern_flags IS NULL;
```

Preserve the same logic in both durability layers:
- `/root/.hermes/wolfy/postgres_init.sql`
- canonical `/root/.hermes/scripts/mike_safe_autorepair.py`, then run it to sync `/root/.hermes/wolfy/mike_safe_autorepair.py` and Mike/Clerky profile copies.

Update `wolfy_sync_scanner_results_aliases()` so new/updated rows populate `pattern_flags` from `notes->'pattern_flags'` or a compact object built from existing pattern/trend fields. Refresh the trigger with `DROP TRIGGER IF EXISTS ...; CREATE TRIGGER ... BEFORE INSERT OR UPDATE OF ... pattern_flags, squeeze_flag ...`.

## Verification
Run:

```bash
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py   # second run should be silent
python3 -m py_compile \
  /root/.hermes/scripts/mike_safe_autorepair.py \
  /root/.hermes/wolfy/mike_safe_autorepair.py \
  /root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py \
  /root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py
psql -d wolfy -c "select column_name,data_type from information_schema.columns where table_name='scanner_results' and column_name in ('pattern_flags','metadata','volume') order by column_name;"
psql -d wolfy -c "select id, ticker, pattern_flags from scanner_results order by id desc limit 3;"
```

Expected: second autorepair run silent, compile passes, `pattern_flags` appears as `jsonb`, and recent rows return compact JSON such as `{"pattern":"gap_up_reversal"}` or `{"pattern":"none"}`.

## Reporting nuance
If just-due no-agent cron jobs remain listed while the active Mike LLM ops run is holding/touching `/root/.hermes/cron/.tick.lock`, treat that as the known active-tick artifact. Verify direct script smokes and poll later rather than declaring the scheduler stuck.