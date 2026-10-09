# Wolfy loop_metrics compatibility aliases (2026-07-15)

## Trigger
Mike/optimizer ops probes failed after a plan-only budget-gated run because a diagnostic query expected `loop_metrics.value_numeric`, while the canonical table used `metric_value` with `metric_key` and `captured_at`.

Representative stale log pattern:

```text
ERROR: column "value_numeric" does not exist
```

## Durable fix pattern
Use non-destructive compatibility aliases instead of rewriting canonical writers:

- `loop_metrics.created_at` mirrors canonical `captured_at`
- `loop_metrics.metric_name` mirrors canonical `metric_key`
- `loop_metrics.value_numeric` mirrors canonical `metric_value`

Preserve the aliases in all layers that can recreate/repair the table:

- `/root/.hermes/wolfy/guardian/budget_gate.py`
- `/root/.hermes/wolfy/guardian/config_guardian.py`
- `/root/.hermes/wolfy/postgres_init.sql`

Recommended SQL shape:

```sql
ALTER TABLE loop_metrics ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
ALTER TABLE loop_metrics ADD COLUMN IF NOT EXISTS metric_name TEXT;
ALTER TABLE loop_metrics ADD COLUMN IF NOT EXISTS value_numeric NUMERIC;

UPDATE loop_metrics
SET created_at = COALESCE(created_at, captured_at),
    metric_name = COALESCE(metric_name, metric_key),
    value_numeric = COALESCE(value_numeric, metric_value)
WHERE created_at IS NULL OR metric_name IS NULL OR value_numeric IS NULL;

CREATE OR REPLACE FUNCTION wolfy_sync_loop_metrics_aliases()
RETURNS trigger AS $$
BEGIN
  NEW.created_at := COALESCE(NEW.created_at, NEW.captured_at, now());
  NEW.metric_name := COALESCE(NEW.metric_name, NEW.metric_key);
  NEW.value_numeric := COALESCE(NEW.value_numeric, NEW.metric_value);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_loop_metrics_aliases ON loop_metrics;
CREATE TRIGGER trg_loop_metrics_aliases
  BEFORE INSERT OR UPDATE OF captured_at, metric_key, metric_value, created_at, metric_name, value_numeric
  ON loop_metrics
  FOR EACH ROW EXECUTE FUNCTION wolfy_sync_loop_metrics_aliases();

CREATE INDEX IF NOT EXISTS idx_loop_metrics_key_time ON loop_metrics(metric_key, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_loop_metrics_name_time ON loop_metrics(metric_name, created_at DESC);
```

## Verification

Run real checks after patching:

```bash
python3 -m py_compile /root/.hermes/wolfy/guardian/budget_gate.py /root/.hermes/wolfy/guardian/config_guardian.py
psql -d wolfy -v ON_ERROR_STOP=1 -f /root/.hermes/wolfy/postgres_init.sql
psql -d wolfy -c "select coalesce(max(value_numeric),0) as latest_gateway_healthy from loop_metrics where metric_name='gateway_healthy'; select count(*) filter (where created_at is null or metric_name is null) as unsynced_aliases from loop_metrics;"
WOLFY_BUDGET_SIMULATED_TOKENS_TODAY=1000 WOLFY_BUDGET_SIMULATED_HEADROOM_PCT=90 WOLFY_BUDGET_IGNORE_AUTH=1 python3 /root/.hermes/wolfy/guardian/budget_gate.py --no-record
python3 /root/.hermes/wolfy/guardian/config_guardian.py --home /root/.hermes --skip-cli
cd /root/.hermes/wolfy && python3 -m pytest -q test_config_guardian.py
```

For the trigger smoke, insert and delete a temporary row:

```sql
insert into loop_metrics(category, metric_key, metric_value, notes)
values ('ops-smoke','alias_smoke',42,'mike alias trigger smoke')
returning id, created_at is not null as has_created_at, metric_name, value_numeric;

delete from loop_metrics where category='ops-smoke' and metric_key='alias_smoke';
```

## Reporting nuance

If the aggregate usage snapshot says token volume is over threshold but the dedicated usage-limit watchdog runs silently twice and production auth is healthy, treat it as volume context, not an active quota incident. Do not pause jobs or alert unless the watchdog/logs show concrete active usage-limit evidence.