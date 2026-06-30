# Wolfy Postgres universe compatibility view / enabled alias (2026-06-27)

## Trigger

Mike ops saw historical/ad-hoc diagnostic probes fail after the live universe tables moved to the Postgres-primary schema:

- `ERROR: relation "universe" does not exist`
- `ERROR: column "enabled" does not exist`

Canonical live tables were healthy:

- `universe_symbols(symbol, name, source, sector, is_etf, last_seen, active, wolfy_tier, tier_source, backfill_priority, backfill_enabled, tier_notes)`
- `universe_backfill_targets(symbol, tier, source, name, priority, active, reason, selected_at)`

The failure was diagnostic/query drift, not data loss.

## Safe repair pattern

Use non-destructive aliases/views rather than rewriting canonical paths:

```sql
ALTER TABLE universe_backfill_targets ADD COLUMN IF NOT EXISTS enabled boolean;
UPDATE universe_backfill_targets SET enabled=active WHERE enabled IS NULL;

CREATE OR REPLACE FUNCTION wolfy_sync_universe_backfill_targets_aliases()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.enabled IS NULL THEN
    NEW.enabled := COALESCE(NEW.active, true);
  END IF;
  IF NEW.active IS NULL THEN
    NEW.active := COALESCE(NEW.enabled, true);
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_universe_backfill_targets_aliases_biu ON universe_backfill_targets;
CREATE TRIGGER trg_universe_backfill_targets_aliases_biu
  BEFORE INSERT OR UPDATE OF active, enabled ON universe_backfill_targets
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_universe_backfill_targets_aliases();

DROP VIEW IF EXISTS universe;
CREATE VIEW universe AS
SELECT
  symbol,
  name,
  source,
  sector,
  is_etf,
  last_seen,
  active,
  active AS enabled,
  wolfy_tier,
  wolfy_tier AS tier,
  tier_source,
  backfill_priority,
  backfill_enabled,
  tier_notes
FROM universe_symbols;
```

Preserve the repair in both durable schema layers:

- `/root/.hermes/wolfy/postgres_init.sql`
- canonical `/root/.hermes/scripts/mike_safe_autorepair.py`

Then run the global autorepair wrapper so it syncs:

- `/root/.hermes/wolfy/mike_safe_autorepair.py`
- `/root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py`
- `/root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py`

## Verification

Use exact alias probes plus normal smoke checks:

```bash
psql -d wolfy -c "select count(*) as universe_rows, count(*) filter (where enabled) as enabled_universe from universe; select count(*) as targets, count(*) filter (where enabled) as enabled_targets from universe_backfill_targets; select coalesce(wolfy_tier,'NULL') as tier,count(*) from universe group by 1 order by 2 desc limit 10;"
python3 -m py_compile /root/.hermes/scripts/mike_safe_autorepair.py /root/.hermes/wolfy/visible_progress_ledger.py
/root/.hermes/scripts/mike_safe_autorepair.py
/root/.hermes/scripts/mike_safe_autorepair.py
cd /root/.hermes/wolfy && python3 -m pytest -q test_visible_progress_ledger.py test_wolfy_tiered_universe.py -o 'addopts='
```

Expected healthy shape from the repair session:

- `universe`: 10,483 rows / 10,483 enabled
- `universe_backfill_targets`: 1,356 rows / 1,356 enabled
- Tier visibility includes `small_cap`, `mid_cap`, `large_cap`, `blue_chip`, `etf_core`, and unclassified `NULL` rows
- Autorepair first run may sync wrappers; second run should be silent
- Targeted tests passed: `5 passed`

## Pitfalls

- Treat missing `universe`/`enabled` in ad-hoc probes as compatibility drift, not a reason to rename canonical live tables or duplicate mutable universe state.
- Use `DROP VIEW IF EXISTS ...; CREATE VIEW ...` for compatibility views so column-list changes do not hit `CREATE OR REPLACE VIEW` column rename/drop limitations.
- Patch canonical `/root/.hermes/scripts/mike_safe_autorepair.py` first; Wolfy/profile copies are overwritten by the sync step.
- If cron `Next run` looks stale while the current Mike ops LLM run is active and `/root/.hermes/cron/.tick.lock` was just touched, do not report the scheduler stuck solely from that listing. Verify direct script smokes and poll after the active run exits.
