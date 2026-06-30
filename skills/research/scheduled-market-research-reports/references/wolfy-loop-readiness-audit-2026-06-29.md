# Wolfy loop-readiness audit pattern — 2026-06-29

Use when the user asks whether Wolfy/Hermes is “set up correctly to loop,” “making progress,” or similar readiness/progress questions.

## What to check first

1. Cron scheduler/gateway state: verify the gateway is running and count active jobs (`hermes cron status`, plus cron list/all via the cron tool or CLI as available).
2. Separate active script-only jobs from paused LLM-driven jobs. A system can still be looping if deterministic/no-agent jobs are running while LLM jobs are quota-gated.
3. Run/inspect the usage-limit watchdog path before concluding agents stopped. If logs show `credential pool: no available entries (all exhausted or empty)` or related quota/rate-limit events, report LLM-driven progress as gated, not broken.
4. Verify Wolfy Postgres health with `/root/.hermes/wolfy/check_postgres_requirements.py` before making DB-maintenance claims.
5. Query current operational tables directly for freshness. For the EOD price/feature path the relevant tables are `prices`, `features`, and `runs` with date column `dt`; do **not** query nonexistent `eod_prices`/`eod_features` aliases unless a compatibility view has been deliberately added.

Useful status query:

```sql
select 'prices', count(*), max(dt) from prices;
select 'features', count(*), max(dt) from features;
select 'runs', count(*), max(started) from runs;
select job,status,count(*),max(started)
from runs
group by 1,2
order by max(started) desc
limit 8;
```

## EOD ingest timeout interpretation

The script-only EOD after-close ingest cron can fail with `Script timed out after 120s` even when Postgres, features, and other loops are healthy. Treat this as an ingest-window/rate-limit engineering issue, not a total-loop failure.

Fast triage sequence:

- Run the wrapper dry-run for a tiny universe to prove the API/parser path is alive:
  `python /root/.hermes/scripts/wolfy_eod_after_close_ingest.py --dry-run --source massive --tickers SPY,QQQ,IWM --days 30`
- Check `prices`/`features` max `dt` and `runs` status.
- If the full universe times out, recommend/implement smaller ticker shards, incremental-only runs, longer script budget if scheduler supports it, or a bounded background backfill with JSONL logs and a post-verifier. Do not imply completion from a timed-out foreground run.

## Reporting shape

Keep the answer direct:

- `Working:` gateway/cron, Postgres, active no-agent jobs, latest DB dates/counts.
- `Blocked/gated:` LLM-driven jobs paused due provider quota/rate-limit, stale/timed-out EOD ingest, missing approved-strategy gates.
- `Next fix:` one concrete repair target, e.g. shard Massive EOD ingest under cron timeout and keep script-only loops running while LLM provider pool recovers.

This is a readiness audit, not a market report. Avoid broad roadmaps; answer whether the loop is actually making progress and what single bottleneck prevents full autonomy.