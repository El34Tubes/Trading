# Wolfy / Trading Research System Goal

## Mission

Build Wolfy into an EOD-only, Postgres-backed quantitative research desk for U.S. stocks and ETFs that can continuously improve, screen, validate, and report trade candidates while preserving strict human control over any strategy approval or trade execution.

## Operating Constitution

- **EOD only:** decisions are based on closing data; no intraday trade execution logic.
- **No auto-execution:** no broker authority, no money movement, no live order placement.
- **Human-gated approval:** deterministic research can promote strategies to `candidate`, but only the user can mark a strategy `approved`.
- **Deterministic signal path:** scripts compute prices, features, signals, risk checks, and setup eligibility. LLMs interpret/rank/explain; they do not invent numeric edge.
- **Postgres source of truth:** live operational data should use PostgreSQL, not legacy SQLite.
- **Quiet is valid:** no setup is better than forcing a weak setup.

## User Trading Constraints

- Robinhood-tradable U.S. stocks and ETFs only.
- Long-only equities/ETFs; no shorts.
- Options allowed only as defined-risk paper-trading structures.
- Max 3 concurrent positions.
- Stops/invalidation required.
- Start with a $5,000 paper-trading account.
- Avoid PDT problems.
- Avoid foreign markets/names with high fraud, pump-and-dump, manipulation, or government-interference risk.

## Target Workflow

1. **Data ingestion**
   - Pull adjusted EOD OHLCV data.
   - Maintain adequate historical depth per ticker.
   - Recompute deterministic features and signals after ingest.

2. **Screening and lead generation**
   - Use deterministic scanners to identify liquid, tradable U.S. opportunities.
   - Treat scanner/Alpha Search output as leads only, not recommendations.

3. **Strategy validation**
   - Validate deterministic strategies with historical depth, backtests, walk-forward/OOS checks, risk gates, and setup counts.
   - Strategies can become `candidate`; they are not actionable until explicitly user-approved.

4. **Recommendation pipeline**
   - Wolfy proposes only approved-strategy-backed setups.
   - Sentinel challenges/rejects/modifies candidates.
   - Yang provides technical entry/exit review.
   - Paper ledger records recommendations, paper trades, stops, outcomes, and lessons.

5. **Reporting**
   - Reports should be brief, factual, and broker-style.
   - Separate FACT from JUDGMENT.
   - Clearly label watch-only/candidate/rejected/approved states.
   - Report concrete progress: DB freshness, coverage, strategy gate status, blockers, and next action.

## Current Architecture Direction

- PostgreSQL `wolfy` database is the operational source of truth.
- Script-only cron jobs should handle data ingest, features, signals, backfills, watchdogs, and accounting wherever possible.
- LLM cron jobs are reserved for synthesis, ranking, exception handling, and user-facing reports.
- Token use should be minimized by caching, deterministic scripts, and compact structured context.
- Cron-facing wrapper filenames should stay stable; shared logic should live behind them in reusable Wolfy modules.

## Near-Term Engineering Priorities

1. Keep EOD ingest shards and bounded tiered backfill running reliably.
2. Maintain visible progress ledger for data freshness, tier coverage, strategy readiness, paper/accountability gates, and blockers.
3. Finish Postgres-only migration for live consumers.
4. Improve deterministic strategy validation only after sufficient data coverage is present.
5. Expand paper-trade accountability once approved-strategy gates are satisfied.

## Non-Goals

- No live trading automation.
- No broker API execution authority.
- No forced trade ideas.
- No LLM-generated numeric edge without deterministic backing.
- No approval of strategies without explicit user decision.
- No destructive database/package changes without guard checks and approval where needed.
