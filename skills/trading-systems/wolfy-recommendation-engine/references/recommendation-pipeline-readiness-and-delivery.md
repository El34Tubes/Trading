# Recommendation Pipeline Readiness and Delivery Policy

## Purpose

Use this when Wolfy has fresh-looking market data but produces no recommendations, or when scheduled jobs are posting too much routine status to Discord.

## Recommendation readiness is a chain, not one flag

Before reporting "no qualifying setups," verify every link:

1. **Data availability**
   - Compare the current New York date with `max(prices.dt)` and `max(features.dt)`.
   - Wolfy's delayed/free Massive plan intentionally defaults to the previous business day because same-calendar-day daily aggregates have returned `403 NOT_AUTHORIZED`.
   - Do not label the expected T+1 policy as a failed ingest when cron itself succeeded.
   - Do not enable `WOLFY_MASSIVE_ALLOW_CURRENT_DAY=1` unless the provider plan is known to authorize current-day aggregates. A paid/current-day source or a verified alternate feed is required for same-day post-close recommendations.

2. **Strategy governance**
   - Read live `strategies.status`, `latest_oos_verdict`, `last_validated`, `approval_scope`, and `paper_recommendation_approval`.
   - Do not trust a skill's historical statement that a strategy is currently approved; live Postgres is authoritative.
   - Paper eligibility requires `status='approved'`, `approval_scope='paper_only_no_live_execution'`, and `paper_recommendation_approval=true`.

3. **Revalidation semantics**
   - `run_monthly_strategy_revalidation()` must re-run the same deterministic setup-outcome gate before its conservative demotion pass.
   - Auto-reactivation is allowed only when all are true: the strategy is `candidate`, the fresh gate passes, prior metadata has `paper_recommendation_approval=true`, `approval_scope='paper_only_no_live_execution'`, `future_same_gate_auto_activation_allowed=true`, and the prior gate itself passed. A changed or previously failed gate is not auto-approved.
   - Persist an auditable `backtests` row and `research_log` result for every revalidation.
   - Keep three dates distinct:
     - `validation_run_date` / `last_validated`: when governance actually reran the gate;
     - `validated_through`: latest stored market bar available for the strategy's signal tickers, capped by the requested as-of date;
     - backtest `window_end`: latest signal/outcome observation included.
   - Never label `validated_through` with the wall-clock date when delayed EOD bars end earlier. Using market-data coverage as `last_validated`, or wall-clock time as data coverage, produces false staleness or false freshness.
   - After fresh revalidation, demote any still-approved strategy whose current gate fails or whose validation remains stale. Never restore a strategy by a bare `UPDATE status='approved'`.

4. **Signal universe coverage**
   - Compare the scheduled signal universe with the universe used in validation.
   - A small core universe can produce far fewer signals than a broad historical validation universe even when the strategy is healthy.
   - Expand only to active, sufficiently backfilled, liquid, eligible U.S. symbols and preserve risk exclusions and point-in-time constraints.

5. **Downstream writer/logger wiring**
   - Confirm the scheduled chain actually invokes, in order:
     1. ingest/features;
     2. signals/setups;
     3. `write_approved_paper_recommendations()`;
     4. `log_approved_paper_recommendation_trades()`;
     5. `review_open_paper_trade_setups()`;
     6. concise actionable summary.
   - Generating signals/setups alone does not create recommendation or paper-trade rows.
   - Keep the chain deterministic, scoped to the current signal date/tickers, idempotent, and hard-coded to create zero broker orders.

## How to answer "what are today's recommendations?"

Use this decision order:

- If current eligible recommendation rows exist: report them with signal date, entry, invalidation, target, sizing, and paper/live status.
- If data is complete and the eligible strategy ran but produced zero qualifiers: say **no trade / stay in cash**.
- If data, strategy approval, universe coverage, or downstream wiring is incomplete: say **no trustworthy recommendation available** and name the blocker. Do not misrepresent an incomplete pipeline as a clean no-signal result.
- Ignore legacy `pending_review` rows lacking approved-strategy provenance, signal date, entry, stop, and target.

## Discord delivery policy

For this user's Wolfy system:

- Discord/origin delivery is reserved for:
  - actual progression updates;
  - actionable recommendations;
  - decisions or approvals required from the user;
  - exceptional failures that block progress and need user action.
- Routine health checks, watchdogs, usage accounting, storage metrics, stale-coordination cleanup, autorepair status, and scanner snapshots should continue running but use `deliver='local'`.
- Clerky may continue local Kanban allocation, but do not schedule Clerky activity reports to Discord/origin.
- Script-only jobs should emit empty stdout when there is nothing actionable; empty stdout is silent.
- Before removing a cron job, list jobs first and use the returned job ID. Prefer changing routine jobs to local delivery when their background work is still useful.
