# Wolfy paused LLM jobs: manual resume + catch-up report pattern (2026-06-30)

## Trigger

User asked “Nothing today?” after no visible Wolfy report appeared.

## Facts observed

- Hermes gateway/cron scheduler was running and no-agent/script-only jobs were active.
- The usage-limit watchdog ran silently twice, meaning no active quota/rate-limit block was detected at that moment.
- Several LLM-driven/user-visible jobs were still paused from a prior usage-limit event even though the active limit had cleared:
  - Wolfy EOD after-close screening report
  - Jonah autonomous knowledge builder
  - Clerky activity report
  - Sentinel post-EOD reviewer
  - Yang technical analyst
  - Alpha Search report
  - Mike LLM ops loop
  - Daily optimization planner
- Script-only backend still ran: EOD ingest shards, deterministic signals, scanner snapshots, storage/autorepair/cleanup/embedding jobs.
- Deterministic EOD signals produced research-only signals but zero approved-gated setups; no capital/paper setup should be presented.
- Latest stored `prices`/`features`/`signals` were still one market day behind (`2026-06-29`) even after the 6/30 cron run; report had to state the actual data basis rather than implying fresh 6/30 close data.

## Correct response pattern

1. Load the market-report skill, then audit before answering:
   - `hermes --profile default cron status`
   - `hermes --profile default cron list --all`
   - run `/root/.hermes/scripts/wolfy_usage_limit_watchdog.py` twice; second run should be silent if no new limit event remains.
   - inspect same-day cron outputs for EOD shards, deterministic signals, scanner snapshots, and tiered backfill.
   - query Postgres `prices`, `features`, `signals`, `strategies`, and `setups` for max `dt`, strategy status, signal counts, and setup counts.
2. If the watchdog is silent/no active provider limit but LLM jobs are paused, resume the paused LLM-driven jobs explicitly with the cronjob tool. Do not rely on future watchdog ticks to repair the state immediately.
3. If a scheduled visible report was missed and the user is asking about it, manually run the report job once after resuming it. Verify the cron output and delivery log before saying it was delivered.
4. Report in two layers:
   - `Visible/report layer`: paused or resumed, catch-up report delivered or not delivered.
   - `Silent backend`: which script-only jobs actually ran.
5. For Hermes-EOD, if deterministic signals exist but all strategies are `research_only` and setups are zero, state: `NO SETUP / WATCHLIST ONLY`; `candidate/research_only is not approved`; no capital/paper trade proposal.
6. If latest price/signal `dt` lags the current calendar date, state the actual data basis explicitly and treat it as a data freshness issue, not a trade signal.

## Pitfalls

- Do not tell the user “nothing happened” just because the visible report was absent. The backend may have run while LLM/report jobs were paused.
- Do not assume a silent usage watchdog automatically resumed all jobs. Verify cron job enabled/paused state directly.
- Do not fabricate the missed report content. Either manually run the actual cron job and verify output/delivery, or report why it could not be run.
- Do not convert research-only deterministic signals into recommendations. The approved-strategy gate still blocks setups.
