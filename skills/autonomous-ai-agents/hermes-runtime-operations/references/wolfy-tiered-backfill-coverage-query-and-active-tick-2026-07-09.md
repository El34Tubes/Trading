# Wolfy tiered backfill coverage query + active-tick advance (2026-07-09)

Context: Mike ops cron saw stale/recent log warnings around the bounded tiered EOD history backfill and an ad-hoc status SQL query using `universe_backfill_targets.latest_dt`. The live table did not have that column; coverage facts live in `prices` and should be joined in, not added as a durable alias unless a real consumer requires it.

## Durable lesson

For tiered backfill status, do **not** query `universe_backfill_targets.latest_dt`. Derive coverage from `prices`:

```sql
WITH coverage AS (
  SELECT p.ticker AS symbol,
         count(*)::int AS bars,
         max(p.dt) AS latest_dt
  FROM prices p
  GROUP BY p.ticker
)
SELECT coalesce(ubt.tier_source, ubt.tier, 'unknown') AS tier,
       count(*) AS targets,
       count(*) FILTER (WHERE coalesce(ubt.backfill_enabled, ubt.enabled, ubt.active)) AS enabled,
       count(*) FILTER (WHERE c.latest_dt IS NULL) AS no_prices,
       count(*) FILTER (WHERE c.latest_dt >= current_date - interval '5 days') AS currentish,
       min(c.bars) AS min_bars,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY c.bars) AS median_bars
FROM universe_backfill_targets ubt
LEFT JOIN coverage c ON c.symbol = ubt.symbol
GROUP BY 1
ORDER BY 1;
```

This preserves the Postgres-primary schema instead of creating a convenience `latest_dt` alias on the target table.

## Safe active-tick pattern

If a no-agent bounded tiered backfill is just due while an LLM Mike ops cron session is active, treat the stale `Next run` timestamp as an active-tick artifact until proven otherwise. It is safe to manually run the bounded wrapper as a smoke/advance step:

```bash
python3 /root/.hermes/scripts/wolfy_tiered_backfill_bounded.py
```

Then report concrete deltas instead of declaring scheduler failure:

- tickers advanced
- `bars_fetched`
- ingest/feature run IDs
- before/after missing/currentish counts from the coverage query above

Example observed result: the wrapper advanced mid-cap tickers `FBIN`, `FCFS`, `FCN`, `FFIN`, fetched two 1002-bar batches, and improved mid-cap missing-price targets from `244` to `240`.

## Verification bundle

Use this compact sequence after wrapper/path repairs or stale-log warnings:

```bash
python3 /root/.hermes/wolfy/check_postgres_requirements.py
python3 -m py_compile \
  /root/.hermes/scripts/wolfy_tiered_backfill_bounded.py \
  /root/.hermes/wolfy/wolfy_tiered_backfill_bounded.py \
  /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py
psql -d wolfy -c "select count(*) as stale_started_runs from agent_runs where status='started' and started_at < now() - interval '90 minutes';"
```

If the only open `agent_runs.status='started'` row is the current Mike ops cron session, do not report it as stale ledger noise.
