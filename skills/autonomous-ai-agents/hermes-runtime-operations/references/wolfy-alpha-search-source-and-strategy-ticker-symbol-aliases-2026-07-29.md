# Wolfy alpha_search/source aliases and strategy_rules ticker_symbol compatibility (2026-07-29)

## Trigger
Recent Jonah/Alpha runtime logs showed ad-hoc Postgres probes failing with:

- `ERROR: column "source_table" does not exist` while querying `alpha_search_leads`.
- `ERROR: column "ticker_symbol" does not exist` while querying `strategy_rules`.

These were compatibility-view drift issues, not broken market logic.

## Safe repair pattern
Use non-destructive read-only compatibility aliases rather than changing canonical write paths:

1. In `alpha_search_leads` view, expose provenance aliases from canonical `alpha_leads`:
   - `'alpha_leads'::text AS source_table`
   - `id::text AS source_id`
2. In `strategy_rules` compatibility view, expose:
   - `NULL::text AS ticker_symbol`
   for both the canonical `strategies` branch and the archived `knowledge_chunks` branch.
3. Preserve the same view definition in both:
   - `/root/.hermes/wolfy/postgres_init.sql`
   - `/root/.hermes/scripts/mike_safe_autorepair.py`
4. Run canonical autorepair once to sync copied wrappers:
   - `/root/.hermes/wolfy/mike_safe_autorepair.py`
   - `/root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py`
   - `/root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py`

## Verification commands

```bash
python3 /root/.hermes/scripts/mike_safe_autorepair.py >/tmp/mike_autorepair_1.out 2>/tmp/mike_autorepair_1.err
python3 /root/.hermes/scripts/mike_safe_autorepair.py >/tmp/mike_autorepair_2.out 2>/tmp/mike_autorepair_2.err
wc -c /tmp/mike_autorepair_1.out /tmp/mike_autorepair_1.err /tmp/mike_autorepair_2.out /tmp/mike_autorepair_2.err

psql -d wolfy -v ON_ERROR_STOP=1 \
  -c "select id,ticker,title,source_table,source_id from alpha_search_leads order by id desc limit 3;" \
  -c "select id,name,ticker,ticker_symbol,status,enabled from strategy_rules order by id limit 3;"

psql -d wolfy -v ON_ERROR_STOP=1 -1 -f /root/.hermes/wolfy/postgres_init.sql >/tmp/postgres_init_verify.out 2>/tmp/postgres_init_verify.err
python3 -m py_compile \
  /root/.hermes/scripts/mike_safe_autorepair.py \
  /root/.hermes/wolfy/mike_safe_autorepair.py \
  /root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py \
  /root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py
```

Expected state:

- Exact alias probes return rows.
- `postgres_init.sql` applies cleanly with `ON_ERROR_STOP`.
- First autorepair may report syncing wrapper copies; second run should be silent.
- Coordination checks still show no stale started runs or fresh duplicate-claim noise.

## Reporting nuance
If the aggregate usage snapshot prints a token-threshold line but the dedicated usage-limit watchdog runs silently twice, report it as usage-volume context only. Do not pause jobs or call it an active quota incident unless the watchdog/logs show a concrete active limit event.