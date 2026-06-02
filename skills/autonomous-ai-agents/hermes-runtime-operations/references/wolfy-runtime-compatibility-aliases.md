# Wolfy runtime compatibility aliases

Session distilled: 2026-06-02 Mike autonomous environment triage.

Use this reference when Wolfy cron/context diagnostics fail because an older durable SQLite/Postgres schema lacks non-destructive convenience columns that newer prompts/scripts query.

## Pattern

1. Treat recent log tails as leads, not truth. Re-run the exact context script or query first.
2. If a query expects alias columns on an existing table, prefer adding nullable/default alias columns and backfilling from canonical fields. Do **not** drop/recreate tables or rewrite user data.
3. Add triggers or an idempotent migration helper in the schema/init script so the aliases stay populated on future inserts/updates.
4. Re-run the context script and a direct query showing the alias shape works.
5. If smoke-test context scripts create `agent_runs.status='started'` rows, finish those temporary rows with `records_created=0` and a summary so they do not become stale-run noise.

## Concrete Wolfy example: `strategy_rules`

Failure shape:

```sql
select id,name,status,asset_class,description from strategy_rules where status='active';
-- no such column: name
```

Safe compatibility repair:

```sql
ALTER TABLE strategy_rules ADD COLUMN name TEXT;
ALTER TABLE strategy_rules ADD COLUMN status TEXT DEFAULT 'active';
ALTER TABLE strategy_rules ADD COLUMN asset_class TEXT DEFAULT 'equity_etf_process';
UPDATE strategy_rules
SET name = COALESCE(name, rule_name),
    status = COALESCE(status, CASE WHEN enabled=1 THEN 'active' ELSE 'inactive' END),
    asset_class = COALESCE(asset_class, 'equity_etf_process');
```

Then add/keep idempotent init-script logic that checks `PRAGMA table_info(strategy_rules)` and adds only missing columns. Add triggers such as `trg_strategy_rules_alias_insert` and `trg_strategy_rules_alias_update` to keep aliases synchronized from `rule_name`/`enabled`.

Verification commands:

```bash
python3 /root/.hermes/wolfy/init_wolfy_db.py
sqlite3 /root/.hermes/wolfy/wolfy.db "select id,name,status,asset_class,description from strategy_rules where status='active' limit 1;"
python3 /root/.hermes/wolfy/wolfy_report_context.py >/tmp/report_ctx.out 2>/tmp/report_ctx.err; echo $?
```

If the context-script smoke created temporary Postgres runs:

```bash
python3 /root/.hermes/wolfy/wolfy_agent_cli.py run-finish --run-id <id> --status completed --records-created 0 --summary 'Mike smoke-test context invocation completed without DB writes'
```

## Dependency fix example: document extraction

If Jonah/source-ingestion logs show `pdftotext: command not found`, install the OS package and verify the binary version:

```bash
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y poppler-utils
pdftotext -v 2>&1 | head -1
```

Capture this as an install/setup repair, not as a persistent claim that document ingestion is broken.
