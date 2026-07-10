# Mike active-tick backfill and universe-symbol triage (2026-07-07)

Context: scheduled Mike ops run started while several default-profile no-agent jobs were due. `hermes --profile default cron list --all` still showed stale `Next run` timestamps for Jonah and the bounded tiered backfill, but gateway/cron was running and `/root/.hermes/cron/.tick.lock` had just been touched by the active Mike LLM cron session.

## Durable lessons

- Treat just-due/stale `Next run` timestamps during an active Mike LLM ops run as an active-tick artifact until proven otherwise. Cross-check gateway process, tick-lock mtime, and agent log lines for the current `cron_fdfd...` session before declaring scheduler failure.
- For due no-agent jobs that are safe and bounded, it is OK to run the exact script manually as a smoke/advance step while the active tick is occupied, then verify DB/state deltas. Example: `python3 /root/.hermes/scripts/wolfy_tiered_backfill_bounded.py` advanced mid-cap coverage by four tickers and exited 0.
- If a direct status SQL query against the read-only `universe` compatibility relation fails on `u.ticker`, inspect columns before adding schema aliases. Current relation exposes `symbol`, not `ticker`; use `p.ticker = u.symbol` for price joins unless a real durable consumer requires a `ticker` alias.
- Recent error tails from Jonah scratch probes remain triage leads, not truth. Rerun the exact temp script when it still exists; in this run `/root/.hermes/wolfy/tmp_query_amat_3444.py` exited OK, so no schema change was warranted.

## Verification pattern

```bash
# Cron and active tick context
date -Is
hermes --profile default cron status
stat -c '%n %s %y' /root/.hermes/cron/.tick.lock /root/.hermes/profiles/default/cron/.tick.lock 2>/dev/null || true

# Safe due-job manual smoke/advance
python3 /root/.hermes/scripts/wolfy_tiered_backfill_bounded.py

# Correct universe coverage query shape: universe.symbol, not universe.ticker
psql -d wolfy -c "
select tier,
       count(*) targets,
       count(*) filter (where bar_count >= 495) ready_495,
       count(*) filter (where bar_count is null or bar_count=0) missing,
       min(bar_count) min_bars,
       percentile_cont(0.5) within group (order by bar_count) median_bars
from (
  select coalesce(u.wolfy_tier,u.tier,'unknown') tier,
         u.symbol,
         count(p.*) bar_count
  from universe u
  left join prices p on p.ticker = u.symbol
  where coalesce(u.active,true) and coalesce(u.enabled,true)
  group by 1,2
) s
group by 1
order by 1;"

# Scratch probe triage: rerun before schema changes
python3 /root/.hermes/wolfy/tmp_query_amat_3444.py >/tmp/tmp_query_amat_3444.out
```

## Reporting nuance

If all health checks are clean and the only anomalies are due timestamps during the current LLM cron session, report the manual bounded advancement (if any) and classify scheduler staleness as active-tick artifact. Do not alert that cron is stuck unless due jobs remain stale after the active LLM run exits.
