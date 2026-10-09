# Wolfy strategies.metadata compatibility alias (2026-07-16)

## Trigger

Mike ops saw a fresh optimizer/ad-hoc strategy probe fail with:

```text
ERROR: column "metadata" does not exist
... select count(*) from strategies where coalesce((metadata->>...)
```

The live canonical `strategies` table used `params jsonb`; read-only probes and some optimizer SQL had drifted to `metadata`.

## Safe repair pattern

Do **not** rename canonical strategy fields or rewrite consumers broadly. Add a nullable, non-destructive compatibility alias:

```sql
ALTER TABLE strategies ADD COLUMN IF NOT EXISTS metadata JSONB;
UPDATE strategies
SET metadata = COALESCE(metadata, params, '{}'::jsonb)
WHERE metadata IS NULL;

CREATE OR REPLACE FUNCTION wolfy_sync_strategies_aliases()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.metadata IS NULL THEN
    NEW.metadata := COALESCE(NEW.params, '{}'::jsonb);
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_strategies_aliases_biu ON strategies;
CREATE TRIGGER trg_strategies_aliases_biu
  BEFORE INSERT OR UPDATE OF params, metadata ON strategies
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_strategies_aliases();
```

Preserve the same alias in all layers that can recreate/repair strategy schema:

- `/root/.hermes/wolfy/postgres_init.sql`
- canonical `/root/.hermes/scripts/mike_safe_autorepair.py`
- Wolfy-local/profile copies synced by autorepair
- local table initializers such as `/root/.hermes/wolfy/eod_backtest.py` and `/root/.hermes/wolfy/eod_signals.py`

Patch the canonical global autorepair source first, then run it so Wolfy/Mike/Clerky copies sync. If the live DB already has the alias but preservation layers do not, patch preservation anyway.

## Verification transcript shape

Use real checks, not just successful ALTER output:

```bash
psql -v ON_ERROR_STOP=1 -d wolfy -f /root/.hermes/wolfy/postgres_init.sql
psql -d wolfy -c "
  select count(*) strategies_metadata_ok from strategies where metadata is not null;
  select count(*) strategy_metadata_probe from strategies where coalesce((metadata->>'source'), status, '') <> '';
  select count(*) strategy_rules_metadata_ok from strategy_rules where metadata is not null;
"
python3 -m py_compile \
  /root/.hermes/scripts/mike_safe_autorepair.py \
  /root/.hermes/wolfy/mike_safe_autorepair.py \
  /root/.hermes/wolfy/eod_backtest.py \
  /root/.hermes/wolfy/eod_signals.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py >/tmp/autorepair1.out
python3 /root/.hermes/scripts/mike_safe_autorepair.py >/tmp/autorepair2.out
wc -c </tmp/autorepair2.out   # should be 0
cd /root/.hermes/wolfy && python3 -m pytest test_eod_backtest.py test_eod_signals.py test_visible_progress_ledger.py -q
```

Expected live verification from the repair session:

```text
strategies_metadata_ok = 3
strategy_metadata_probe = 3
strategy_rules_metadata_ok = 37
autorepair second run = silent
pytest: 9 passed total across eod_backtest/eod_signals/visible_progress_ledger
```

## Pitfalls

- This is durable schema drift only when a real probe expects `strategies.metadata`; do not add aliases for one-off malformed SQL if the exact probe already passes.
- Keep canonical writes using `params`; `metadata` is compatibility for probes/LLM-written SQL.
- Preserve the fix in both schema init and autorepair, otherwise a future repair/init cycle can silently regress the alias.
- `strategy_rules` is a read-only compatibility view over `strategies` plus archived `knowledge_chunks`; keep exposing `metadata` there as `COALESCE(params, '{}'::jsonb)`.
