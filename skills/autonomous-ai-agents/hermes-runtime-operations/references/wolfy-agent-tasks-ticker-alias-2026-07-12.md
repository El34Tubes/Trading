# Wolfy `agent_tasks.ticker` compatibility alias (2026-07-12)

## Trigger
Mike ops log showed ad-hoc Postgres probe failures like:

- `ERROR: column "created_at" does not exist` while querying `agent_tasks`
- `ERROR: column "ticker" does not exist` while querying `agent_tasks`

The live `agent_tasks` table already had `created_at`, but did not expose a scalar `ticker` alias. Canonical ticker storage is `agent_tasks.ticker_symbols text[]`; many scratch/read-only probes expect a single `ticker` column.

## Safe repair pattern
Use a non-destructive compatibility alias, not a rewrite of canonical task schema:

```sql
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS ticker TEXT;
UPDATE agent_tasks
SET ticker = COALESCE(ticker, payload->>'ticker', payload->>'symbol', ticker_symbols[1])
WHERE ticker IS NULL;
```

Preserve the alias in both durability layers:

- `/root/.hermes/wolfy/postgres_init.sql`
- canonical `/root/.hermes/scripts/mike_safe_autorepair.py`

Then run canonical autorepair so it syncs copies under:

- `/root/.hermes/wolfy/mike_safe_autorepair.py`
- `/root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py`
- `/root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py`

## Trigger/payload mirror
Refresh `wolfy_sync_agent_tasks_aliases()` so future inserts/updates set `NEW.ticker` from `payload->>'ticker'`, `payload->>'symbol'`, or `NEW.ticker_symbols[1]`; include `ticker` in `payload` JSON; and add `ticker, ticker_symbols` to the trigger's `UPDATE OF` column list.

## Verification
Run:

```bash
psql -v ON_ERROR_STOP=1 -d wolfy -f /root/.hermes/wolfy/postgres_init.sql
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py   # second run should be silent
python3 -m py_compile /root/.hermes/scripts/mike_safe_autorepair.py \
  /root/.hermes/wolfy/mike_safe_autorepair.py \
  /root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py \
  /root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py
psql -d wolfy -c "select id, agent, task_type, status, ticker, summary, error_message, created_at from agent_tasks order by id desc limit 3;"
psql -d wolfy -c "select count(*) as stale_started_runs from agent_runs where status='started' and started_at < now() - interval '90 minutes';"
```

Successful smokes from the repair run showed:

- exact query shape with `ticker` and `created_at` worked
- `stale_started_runs = 0`
- duplicate-claim noise remained `0`
- embedding sync and stale coordination cleanup were silent
- autorepair second run was silent

## Reporting nuance
Do not report this as a trading/market issue. It is an operations compatibility alias repair. Credential/tool warnings from `hermes doctor` remain setup gaps unless they block the specific Wolfy operations path.