# Wolfy visible-progress audit pattern — 2026-06-18

Trigger: user says they are not seeing progress, asks "where are we at," or questions whether Wolfy/Jonah/Clerky/Sentinel/Yang are still working.

Session lesson:

- Visible progress can stall because LLM-driven report/research jobs are auto-paused by the usage-limit watchdog, while script-only jobs continue running quietly.
- Do not equate missing Discord reports with no backend progress. Audit both layers before answering.
- If the watchdog state shows `limited_active=true`, check whether the provider/device-code/rate limit has already expired. If it has cleared, run the usage-limit watchdog script or resume affected jobs instead of only reporting that they are paused.

Recommended audit sequence:

1. List cron jobs and separate:
   - LLM/report jobs: Wolfy EOD report, Jonah knowledge builder, Alpha Search, Clerky report, Sentinel, Yang, Mike LLM triage.
   - Script-only jobs: storage watchdog, usage watchdog, embeddings sync, stale-coordination cleanup, safe autorepair, intraday scanner snapshots, EOD ingest/features/signals, pre-open monitor, monthly revalidation.
2. Inspect `/root/.hermes/wolfy/usage_limit_watchdog_state.json` for `limited_active`, `limit_detail`, and `paused_llm_jobs`.
3. If the limit is stale/expired, run `/root/.hermes/scripts/wolfy_usage_limit_watchdog.py` and verify the previously paused LLM jobs are enabled again.
4. Verify actual backend progress from Postgres, not SQLite legacy tables:
   - `agent_tasks` status counts and recent queue by `updated_at`.
   - recent `agent_runs` for completed/blocked runs.
   - `prices`, `features`, `signals`, and `setups` row counts/latest dates.
   - latest cron output for EOD ingest/features/signals.
5. For EOD-only Wolfy, treat `0 setups` as a valid outcome when strategies remain `research_only` or approved-strategy gates block setups. Report it as `NO SETUP / WATCHLIST ONLY`, not as a broken pipeline.
6. Answer in direct status form: what stalled, what continued, what was resumed/fixed, current DB counts, next scheduled visible reports, and whether any user action is needed.

Pitfall to avoid: telling the user simply "jobs are scheduled" when the visible LLM layer is paused. The correct response is to verify, repair/resume if safe, and then state the current operational truth plainly.