# Wolfy runs.source alias and eod_feature_runs view repair — 2026-07-20

## Trigger

Mike ops log tail showed an ad-hoc/read-only Postgres probe failing with:

```sql
ERROR: column "source" does not exist
... from runs where source ilike ...
```

Live `runs` rows stored the source in `detail->>'source'`, and the compatibility view `eod_feature_runs` existed but filtered only `job LIKE 'eod-%'`, missing canonical underscore-style jobs such as `eod_price_ingest` and `eod_feature_compute`.

## Safe repair pattern

Add a non-destructive compatibility alias, do not rename canonical fields:

```sql
ALTER TABLE runs ADD COLUMN IF NOT EXISTS source TEXT;
UPDATE runs
SET started_at=COALESCE(started_at, started),
    completed_at=COALESCE(completed_at, finished),
    source=COALESCE(source, NULLIF(detail->>'source', ''))
WHERE started_at IS NULL OR completed_at IS NULL OR source IS NULL;

CREATE OR REPLACE FUNCTION wolfy_sync_runs_aliases()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.started_at IS NULL THEN
    NEW.started_at := NEW.started;
  END IF;
  IF NEW.completed_at IS NULL THEN
    NEW.completed_at := NEW.finished;
  END IF;
  IF NEW.source IS NULL THEN
    NEW.source := NULLIF(NEW.detail->>'source', '');
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_runs_aliases_biu ON runs;
CREATE TRIGGER trg_runs_aliases_biu
  BEFORE INSERT OR UPDATE OF started, finished, started_at, completed_at, detail, source ON runs
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_runs_aliases();
```

Fix `eod_feature_runs` to include both hyphen and underscore EOD job names by using `job LIKE 'eod%' OR job LIKE 'feature%'`, not only `eod-%`.

## Preservation layers patched

Preserve the repair in all schema/autorepair/init layers that can recreate or repair the compatibility surface:

- `/root/.hermes/wolfy/postgres_init.sql`
- `/root/.hermes/wolfy/eod_price_features.py`
- canonical `/root/.hermes/scripts/mike_safe_autorepair.py`
- synced copies under `/root/.hermes/wolfy/`, `/root/.hermes/profiles/mike/scripts/`, and `/root/.hermes/profiles/clerky/scripts/`

Patch canonical global autorepair first, then run it twice so profile copies sync and the second run is silent.

## Verification commands

```bash
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 -m py_compile \
  /root/.hermes/scripts/mike_safe_autorepair.py \
  /root/.hermes/wolfy/mike_safe_autorepair.py \
  /root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py \
  /root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py \
  /root/.hermes/wolfy/eod_price_features.py

psql -d wolfy -v ON_ERROR_STOP=1 -f /root/.hermes/wolfy/postgres_init.sql
psql -d wolfy -v ON_ERROR_STOP=1 \
  -c "select count(*) as eod_feature_runs_rows from eod_feature_runs;" \
  -c "select job, source, count(*) from eod_feature_runs group by job, source order by count(*) desc limit 8;" \
  -c "select count(*) as recent_unit_source_runs from runs where source ilike '%unit-%' and started > now() - interval '10 minutes';"
```

Expected healthy shape from the repair session:

- `eod_feature_runs` returned 2017 rows.
- `eod_price_ingest / massive-adjusted-eod` rows were visible.
- Unit-source rows remained queryable for fixture filtering.
- Exact failing-style `runs where source ilike ...` probe exited cleanly.

## Reporting nuance

If `agent_runs.status='started'` shows exactly the current Mike ops cron session, do not classify it as stale. Exclude/explain the current session and only close older stale runs.