# Wolfy Postgres `strategy_rules` compatibility view (2026-06-12)

## Trigger

Jonah/Wolfy ad-hoc probes during Postgres-primary operations still queried the retired SQLite-era table name `strategy_rules`, e.g.:

```sql
select id,name,status,rule_type,ticker_symbols,description
from strategy_rules
where status='approved' or status='active'
order by id desc
limit 20;
```

In the Postgres-primary schema, canonical EOD strategy state lives in `strategies`, while archived/durable SQLite strategy-rule learning is embedded in `knowledge_chunks` with `source_table='sqlite.strategy_rules'`. The safe repair is a read-only compatibility view, not a new mutable table or a rewrite of canonical strategy write paths.

## Safe repair pattern

Create a non-destructive view named `strategy_rules`:

- first branch: `strategies`, exposing aliases such as `rule_name`, `implementation_status`, `rule_type`, `ticker_symbols`, `description`, `source_basis`, `enabled`, `is_active`, `updated_at`, `asset_class`, `category`, `source_id`, and `rule_text`;
- second branch: `knowledge_chunks` rows where `source_table='sqlite.strategy_rules'` and `source_id` is numeric, parsing the chunk text into common rule fields and assigning high synthetic IDs such as `1000000000 + source_id::bigint`.

Preserve the same `CREATE OR REPLACE VIEW strategy_rules AS ...` in both:

- `/root/.hermes/wolfy/postgres_init.sql`
- `/root/.hermes/scripts/mike_safe_autorepair.py`

Then run the script-only autorepair once so it syncs to:

- `/root/.hermes/wolfy/mike_safe_autorepair.py`
- `/root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py`
- `/root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py`

## Verification commands

```bash
psql -d wolfy -v ON_ERROR_STOP=1 -q -f /root/.hermes/wolfy/postgres_init.sql
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py  # second run should be silent

psql -d wolfy -v ON_ERROR_STOP=1 -c "
select count(*) total, count(*) filter (where is_active) active from strategy_rules;
select id,name,status,rule_type
from strategy_rules
where is_active=true or status='approved'
order by updated_at desc nulls last
limit 5;
"

cd /root/.hermes/wolfy
python3 tmp_strategy_rules.py >/tmp/tmp_strategy_rules.out
python3 tmp_query_strategy.py >/tmp/tmp_query_strategy.out
```

Expected healthy signals from the June 12 repair:

- `strategy_rules` resolved with 323 total rows / 320 active rows.
- `tmp_strategy_rules.py` and `tmp_query_strategy.py` exited 0.
- Postgres guard remained on PostgreSQL 16 with pgvector/vector assumptions unchanged.

## Pitfalls

- Do **not** create a mutable `strategy_rules` table in Postgres just to satisfy probes; that risks splitting canonical strategy state from the EOD `strategies` table.
- Do **not** add alias columns for `knowledge_chunks.embedding_provider`/`embedding_model`; those remain JSONB metadata unless a real consumer requires top-level columns.
- Treat this as a compatibility shim for diagnostics/LLM-authored probes. Live EOD strategy promotion and approval logic should continue to use canonical `strategies`, `signals`, `setups`, and risk-gate tables.
