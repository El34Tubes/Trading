# Mike active-tick budget-gate + bounded backfill advance (2026-07-08 evening)

## Context
A Mike autonomous environment triage cron run started while several default-profile no-agent jobs were just due. `hermes --profile default cron list --all` still showed stale `Next run` timestamps for safe no-agent jobs, and `/root/.hermes/cron/.tick.lock` had just been touched by the active Mike LLM session. The budget gate was also blocking LLM contexts (`BUDGET=block token_cap_exceeded`).

## Pattern
When a just-due no-agent job is stale during the active Mike LLM ops tick:

1. Do **not** immediately report scheduler failure.
2. Confirm the active run is expected ledger noise:
   ```sql
   select agent_name, cron_job_id, status, started_at, now()-started_at as age
   from agent_runs
   where status='started'
   order by started_at desc
   limit 5;
   ```
   A fresh `Mike` row for the current ops cron is expected.
3. Direct-smoke safe no-agent jobs instead of waiting on the ticker:
   - `python3 /root/.hermes/scripts/mike_safe_autorepair.py` twice; second should be silent.
   - `python3 /root/.hermes/scripts/wolfy_usage_limit_watchdog.py` twice; second should be silent.
   - `python3 /root/.hermes/scripts/wolfy_cleanup_stale_agent_coordination.py`; silent exit 0.
   - `bash /root/.hermes/scripts/wolfy_config_guardian.sh`; expect `GUARDIAN=ok ...`.
4. For budget-gated LLM contexts, smoke the wrapper path and require the final non-empty stdout line to be JSON:
   ```bash
   WOLFY_CONTEXT_SMOKE=1 python3 /root/.hermes/scripts/wolfy_hourly_knowledge_context.py
   WOLFY_CONTEXT_SMOKE=1 python3 /root/.hermes/scripts/wolfy_eod_weekly_research_context.py
   ```
   Healthy blocked output ends with:
   ```json
   {"wakeAgent": false, "reason": "budget"}
   ```
5. If the due no-agent job is safe and bounded, manually run it as an advance step and report real state deltas. For tiered backfill, capture before/after counts:
   ```bash
   psql -d wolfy -At -c "select count(*) from prices; select max(dt) from prices;"
   python3 /root/.hermes/scripts/wolfy_tiered_backfill_bounded.py
   psql -d wolfy -At -c "select count(*) from prices; select max(dt) from prices;"
   ```

## Concrete result from this run
Manual bounded tiered backfill exited 0 and advanced real state while LLM work was budget-gated:

- `prices` rows: `267387 -> 269391` (+2,004)
- latest price date stayed `2026-07-07`
- mid-cap tickers loaded: `COKE`, `COLB`, `COLM`, `CPRI`
- mid-cap readiness improved: `72 -> 76` tickers with sufficient history in runner output

## Reporting nuance
Report this as a useful backend advance, not a market-analysis result. If the scheduler still shows stale just-due no-agent timestamps while the current Mike ops run is open, say it is an active-tick artifact **only after** the direct smokes pass. Keep remaining blockers concise: budget gate blocking LLM work is protective behavior; script-only jobs continue.