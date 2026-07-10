# Wolfy tiered backfill: skip current-but-short-history tickers

Date: 2026-07-02

## Trigger

The `Wolfy bounded tiered EOD history backfill` cron job timed out even though the underlying Massive API path worked. Manual smoke showed the runner repeatedly selected the same large-cap targets (`ECHO`, `EXE`) because their stored bar counts were below the readiness threshold (`DEPTH_READY_BARS=495`). They were not true missing-history targets:

- `ECHO`: only 6 bars but latest date was current; likely not enough public history yet.
- `EXE`: ~437 bars with latest date current; naturally cannot reach 495 bars yet.

The old selector treated every `<495 bars` ticker as eligible, so every run could waste batches re-fetching current-but-short names and still not advance the backlog.

## Safe fix pattern

Patch the backfill selector, not the market/trading logic:

1. Keep active/enabled/backfill-enabled guards.
2. Select targets with **no prices** immediately.
3. Select partial-history targets only if their latest stored bar is stale, e.g. `latest_dt < current_date - interval '5 days'`.
4. Keep the cron wrapper bounded below the Hermes script timeout (`max-runtime-seconds` under 120s, small `max-batches`).

Concrete selector shape:

```sql
AND coalesce(t.enabled, true)
AND coalesce(t.backfill_enabled, true)
AND (
  coalesce(p.bars, 0) = 0
  OR (
    coalesce(p.bars, 0) < %s
    AND coalesce(p.latest_dt, DATE '1900-01-01') < CURRENT_DATE - INTERVAL '5 days'
  )
)
```

## Verification commands

```bash
python3 -m py_compile \
  /root/.hermes/wolfy/backfill_tiered_remaining.py \
  /root/.hermes/scripts/wolfy_tiered_backfill_bounded.py

PYTHONPATH=/root/.hermes/wolfy python3 - <<'PY'
import psycopg
from backfill_tiered_remaining import remaining_tickers
with psycopg.connect('dbname=wolfy user=root host=/var/run/postgresql') as conn:
    print(remaining_tickers(conn, 'large_cap', 6, 495))
PY

/root/.hermes/scripts/wolfy_tiered_backfill_bounded.py

psql -d wolfy -c "
with p as (
  select ticker, count(*) bars, max(dt) latest from prices group by ticker
)
select t.tier,
       count(*) targets,
       count(*) filter (where coalesce(p.bars,0)>=495) ready,
       count(*) filter (where coalesce(p.bars,0)>0 and coalesce(p.bars,0)<495) partial,
       count(*) filter (where coalesce(p.bars,0)=0) missing,
       max(p.latest) latest
from universe_backfill_targets t
left join p on p.ticker=t.symbol
where t.active
group by t.tier
order by t.tier;"
```

Expected smoke: the runner selects new missing/stale tickers rather than the current-but-short ones, exits `0`, and the relevant tier's ready count advances when Massive returns enough bars.

## Reporting nuance

If the cron listing still shows the previous timeout while the current Mike LLM ops cron session is running, check the tick lock and agent log before declaring the scheduler stuck. A just-triggered no-agent job may wait until the active LLM cron run exits and releases the tick lock.
