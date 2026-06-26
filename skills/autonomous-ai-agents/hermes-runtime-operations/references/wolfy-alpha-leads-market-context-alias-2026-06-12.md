# Wolfy alpha_leads market_context compatibility alias (2026-06-12)

## Trigger
Jonah cron/tool output showed ad-hoc Postgres probes failing with:

```sql
ERROR: column "market_context" does not exist
```

The failing query shape selected `id, created_at, source_fingerprint, left(thesis,300), market_context` from `alpha_leads`. Live rows already stored the needed value in `raw_payload->'market_context'`.

## Safe repair pattern
Use a non-destructive alias column; do not rewrite canonical payload storage and do not drop/recreate tables.

```sql
ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS market_context JSONB;
UPDATE alpha_leads
SET market_context = COALESCE(market_context, raw_payload->'market_context')
WHERE market_context IS NULL;
```

Update `wolfy_sync_alpha_leads_aliases()` so future rows keep the alias populated:

```sql
IF NEW.market_context IS NULL THEN
  NEW.market_context := NEW.raw_payload->'market_context';
END IF;
```

Refresh the trigger to include the alias column in the `UPDATE OF` list:

```sql
DROP TRIGGER IF EXISTS trg_alpha_leads_aliases_biu ON alpha_leads;
CREATE TRIGGER trg_alpha_leads_aliases_biu
  BEFORE INSERT OR UPDATE OF raw_payload, lead_type, evidence_quality_score,
    company_name, scanner_type, market_context, score ON alpha_leads
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_alpha_leads_aliases();
```

## Preservation layers
Patch every layer that may recreate or validate the schema:

- `/root/.hermes/wolfy/postgres_init.sql`
- `/root/.hermes/wolfy/alpha_search_pipeline.py` local `ensure_alpha_tables_postgres()` initializer
- `/root/.hermes/scripts/mike_safe_autorepair.py`
- `/root/.hermes/wolfy/mike_safe_autorepair.py`
- `/root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py`
- `/root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py`

## Verification commands

```bash
python3 -m py_compile \
  /root/.hermes/wolfy/alpha_search_pipeline.py \
  /root/.hermes/scripts/mike_safe_autorepair.py \
  /root/.hermes/wolfy/mike_safe_autorepair.py \
  /root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py \
  /root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py

/root/.hermes/wolfy/check_postgres_requirements.py
python3 /root/.hermes/wolfy/alpha_search_pipeline.py status
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py

psql -d wolfy -v ON_ERROR_STOP=1 -c \
  "select id,created_at,source_fingerprint,left(thesis,300) thesis, market_context from alpha_leads order by updated_at desc limit 3;"

psql -d wolfy -c \
  "select column_name,data_type from information_schema.columns where table_name='alpha_leads' and column_name in ('company_name','scanner_type','market_context','score') order by column_name;"
```

Expected healthy signs:

- Compile succeeds for all patched scripts.
- Postgres guard remains on allowed PostgreSQL 16 line.
- Alpha pipeline status smoke prints JSON counts.
- Second autorepair run is silent.
- Exact formerly failing query returns rows with JSONB `market_context` where present.
