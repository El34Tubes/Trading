# Wolfy Postgres ad-hoc probe alias drift: agent_tasks.type + strategy_rules.scope (2026-06-19)

## Trigger
Recent Jonah/Wolfy ad-hoc research probes generated SQL shaped like older SQLite-era names:

- `select id,title,type,status,... from agent_tasks ...`
- `select id,name,status,scope,ticker_symbols,... from strategy_rules ...`

The live Postgres schema used canonical names:

- `agent_tasks.task_type`
- `strategy_rules.status` via a read-only compatibility view over `strategies` and archived `knowledge_chunks(source_table='sqlite.strategy_rules')`

This caused `UndefinedColumn` errors in scratch probes even though durable live paths were healthy.

## Safe fix pattern
Add non-destructive compatibility aliases instead of rewriting canonical write paths:

1. Add `agent_tasks.type TEXT` and backfill from `task_type`.
2. Update `wolfy_sync_agent_tasks_aliases()` so new/updated rows keep `type := task_type` when missing and include `type` inside the JSONB `payload` mirror.
3. Add `scope` to the read-only `strategy_rules` compatibility view, mirroring `status` for both:
   - canonical `strategies` rows
   - archived `knowledge_chunks(source_table='sqlite.strategy_rules')` rows
4. Preserve the same DDL in both:
   - `/root/.hermes/wolfy/postgres_init.sql`
   - canonical `/root/.hermes/scripts/mike_safe_autorepair.py`
5. Run `/root/.hermes/scripts/mike_safe_autorepair.py` once to sync Wolfy-local and profile copies, then run it a second time to confirm silence/idempotence.

## Verification commands

```bash
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py   # second run should be silent

psql -d wolfy -v ON_ERROR_STOP=1 \
  -c "select id,title,type,task_type,status,source_fingerprint from agent_tasks order by id desc limit 1;" \
  -c "select id,name,status,scope,ticker_symbols,rule_type,description from strategy_rules order by id desc limit 1;"

python3 -m py_compile \
  /root/.hermes/scripts/mike_safe_autorepair.py \
  /root/.hermes/wolfy/mike_safe_autorepair.py \
  /root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py \
  /root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py
```

Expected result: both alias queries return rows; second autorepair run emits no output; compile check is silent.

## Reporting nuance
Treat the original Jonah scratch-query errors as ad-hoc probe drift unless a live cron/report path is failing. Report the durable fix as an alias-preservation repair, not as market-analysis work or a trading-logic change.
