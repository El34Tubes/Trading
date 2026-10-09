# Mike active-tick backfill manual advance — 2026-07-10

Use when a Mike ops cron run sees default-profile cron jobs that are due/stale while the current LLM ops session is itself active.

## Pattern

1. Do not classify the scheduler as stuck from `hermes --profile default cron status` alone when due no-agent jobs are only a few minutes stale and `/root/.hermes/cron/.tick.lock` was just touched by the active ops run.
2. Verify the safe script-only helpers directly. For bounded tiered backfill, it is acceptable to manually run the exact wrapper as a smoke/advance step during the active tick.
3. Capture concrete data deltas instead of only reporting scheduler state. For tiered backfill, record:
   - tickers advanced
   - bars per ticker
   - first/latest `prices.dt`
   - tier readiness counts using `universe_backfill_targets.symbol` joined to `prices.ticker` (not `ubt.ticker`)
4. Treat budget-gated weekly research as healthy when its smoke ends with final JSON `{"wakeAgent": false, "reason": "budget"}`; report budget gating separately from script-only backend health.
5. If direct smokes are clean but cron list still shows stale due jobs, label it as active-tick artifact/unresolved triage and let the next Mike run verify advancement after the current LLM run exits.

## Verification snippets

```bash
python3 /root/.hermes/scripts/wolfy_tiered_backfill_bounded.py
psql -d wolfy -c "select ticker, count(*) as bars, min(dt) as first_dt, max(dt) as last_dt from prices where ticker in ('NBIX','NFG','NLY','NNN') group by ticker order by ticker;"
psql -d wolfy -c "select tier, count(*) filter (where bar_count >= 495) as ready_495, count(*) filter (where coalesce(bar_count,0)=0) as missing, count(*) as targets from (select ubt.tier, ubt.symbol, count(p.*) as bar_count from universe_backfill_targets ubt left join prices p on p.ticker=ubt.symbol where ubt.active group by ubt.tier, ubt.symbol) s group by tier order by tier;"
WOLFY_CONTEXT_SMOKE=1 python3 /root/.hermes/scripts/wolfy_eod_weekly_research_context.py
```

## Reporting

If the manual smoke advanced real data, do not return `[SILENT]`. Report the concrete ticker/count deltas plus any remaining active-tick caveat. If no data changed and all smokes were silent/clean, `[SILENT]` remains appropriate.
