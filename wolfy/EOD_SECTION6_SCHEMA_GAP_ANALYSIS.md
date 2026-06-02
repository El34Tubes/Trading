# Wolfy / Hermes-EOD Section 6 schema gap analysis

Date: 2026-06-01
Task: t_1b956475
Source: `/root/.hermes/cache/documents/doc_26a12d1486bd_hermes_bootstrap.md`, Section 6.

## Scope and guardrails

- Compared the current local SQLite source of truth at `/root/.hermes/wolfy/wolfy.db` and the current Postgres database `wolfy` against the Hermes-EOD Section 6 schema.
- Ran `/root/.hermes/wolfy/check_postgres_requirements.py` before Postgres changes. Result: PostgreSQL 16.14, `pg_trgm` 1.6, `vector` 0.6.0 all within Wolfy requirements.
- Applied only non-destructive Postgres additions using `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, and seed upserts.
- No destructive migrations were run. No live trading, broker, credential, or money-movement capability was added.

## Section 6 target tables

Target tables from Hermes-EOD Section 6:

- `config`
- `prices`
- `fundamentals`
- `earnings_calendar`
- `features`
- `strategies`
- `signals`
- `setups`
- `backtests`
- `research_log`
- `positions`
- `trades`
- `runs`

## Current SQLite gap before migration

SQLite contained useful Wolfy legacy/accountability tables, but not the Section 6 EOD schema as named:

- Present related tables: `meta`, `market_snapshots`, `scanner_runs`, `scanner_results`, `strategy_rules`, `reports`, `recommendations`, `paper_trades`, `recommendation_outcomes`, `knowledge_sources`, `knowledge_notes`, `system_metrics`, `universe_symbols`, alpha/social/insider/Yang tables.
- Missing exact Section 6 EOD tables: all 13 target names (`config`, `prices`, `fundamentals`, `earnings_calendar`, `features`, `strategies`, `signals`, `setups`, `backtests`, `research_log`, `positions`, `trades`, `runs`).
- SQLite remains a legacy/local source for existing jobs. Do not force-convert it destructively. Future work should dual-write or backfill into Postgres EOD tables with idempotent scripts.

## Current Postgres gap before migration

Before this task, Postgres had the scale-up coordination/search/accountability foundation:

- `agent_tasks`, `agent_runs`, `agent_artifacts`, `knowledge_chunks`, `recommendation_reviews`, `agent_usage_snapshots`, alpha-search tables.
- Missing exact Section 6 EOD data-plane tables: all 13 target names.

## Implemented Postgres additions

Migration applied:

- `/root/.hermes/wolfy/migrations/20260601_eod_section6_schema.sql`

It created the Section 6 EOD tables and supporting indexes:

- `config`
- `prices`
- `fundamentals`
- `earnings_calendar`
- `features`
- `strategies`
- `signals`
- `setups`
- `backtests`
- `research_log`
- `positions`
- `trades`
- `runs`
- `eod_schema_migrations` ledger

Seeded `config` keys:

- `min_dollar_vol`
- `slippage_bps`
- `risk_per_trade`
- `max_portfolio_heat`
- `max_name_weight`
- `max_drawdown_killswitch`
- `max_adv_frac`

Seeded `strategies` rows as `research_only` only:

- `pead`
- `trend_volume_vol_regime`
- `sector_cross_sectional_momentum`

Important: the `strategies.status` schema allows `approved` because Section 6 requires human-approved strategies later, but this migration did not seed or promote any strategy to `approved`.

## Verification performed

Commands run:

```bash
python3 /root/.hermes/wolfy/check_postgres_requirements.py
pytest -q /root/.hermes/wolfy/test_eod_section6_migration.py
psql -d wolfy -v ON_ERROR_STOP=1 -f /root/.hermes/wolfy/migrations/20260601_eod_section6_schema.sql
psql -d wolfy -Atc "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN ('config','prices','fundamentals','earnings_calendar','features','strategies','signals','setups','backtests','research_log','positions','trades','runs') ORDER BY tablename;"
psql -d wolfy -Atc "SELECT name || ':' || status FROM strategies ORDER BY name;"
psql -d wolfy -Atc "SELECT key FROM config WHERE key IN ('min_dollar_vol','slippage_bps','risk_per_trade','max_portfolio_heat','max_name_weight','max_drawdown_killswitch','max_adv_frac') ORDER BY key;"
```

Results:

- Postgres guard passed.
- Migration unit tests passed: `2 passed`.
- Migration applied successfully.
- All 13 Section 6 target tables are present in Postgres.
- All 3 initial strategy rows are `research_only`.
- All 7 risk/config keys are present.

## Non-destructive migration plan for remaining work

1. Keep SQLite unchanged for current jobs until each job has a tested Postgres writer.
2. Add idempotent EOD price ingest into Postgres `prices`; use `ON CONFLICT (ticker, dt) DO UPDATE` only.
3. Add deterministic feature generation from `prices` into `features`; no LLM-generated numeric signals.
4. Add deterministic signal generation into `signals`, restricted to known `strategies` rows.
5. Build a screening context that reads only `strategies.status='approved'` for capital setup proposals. Until a human approves a strategy, generated outputs remain research/watch-only.
6. Backfill legacy SQLite tables only where the mapping is obvious:
   - `scanner_results` can inform `features` after validating data dates and formulas.
   - `scanner_runs`/job wrappers can map to `runs`.
   - `strategy_rules` can inform `research_log`/`strategies` notes, not approvals.
   - `paper_trades` can inform `positions`/`trades` only after operator review because Section 6 marks positions operator-maintained/read-only to agents.
7. Do not drop, rename, or rewrite legacy SQLite tables during the transition.
8. Add compatibility tests before each ingest/backfill script.
