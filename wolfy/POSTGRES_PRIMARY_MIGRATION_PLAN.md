# Wolfy Postgres-Primary Migration Plan

Date: 2026-06-02

## Direction

Wolfy should move from SQLite-first coordination toward Postgres as the primary operational database. SQLite remains a compatibility/fallback source only until each consumer is migrated and verified. No destructive SQLite removal yet; retire reads/writes only after smoke tests and cron verification prove Postgres parity.

## Guardrails

- Run `/root/.hermes/wolfy/check_postgres_requirements.py` before Postgres package/schema maintenance.
- Keep PostgreSQL on the approved 16.x line; no major upgrade or destructive migration without explicit user approval.
- No live brokerage, no money movement, no auto-execution.
- EOD framework remains governing: closing-data decisions, next-session human execution, deterministic signals/risk checks, LLM for explanation/ranking only.
- Existing SQLite tables may stay as historical compatibility until Postgres consumers are complete.

## Target source-of-truth split

Postgres primary:

- agent coordination: `agent_tasks`, `agent_runs`, `agent_artifacts`
- knowledge/search: `knowledge_chunks`, future embedding metadata
- EOD market data: `prices`, `features`, `fundamentals`, `earnings_calendar`
- strategy pipeline: `strategies`, `signals`, `setups`, `backtests`, `research_log`, `runs`
- trading/accountability loop: `positions`, `trades`, `recommendation_reviews`
- alpha lead pipeline: `alpha_search_reports`, `alpha_leads`, `alpha_lead_evidence`, `alpha_handoffs`
- config/risk: `config`

SQLite compatibility/fallback until migrated:

- legacy `knowledge_sources`, `knowledge_notes`, `strategy_rules`
- legacy `scanner_runs`, `scanner_results`, `market_snapshots`
- legacy `reports`, `recommendations`, `paper_trades`, `recommendation_outcomes`
- any script still importing `sqlite3` directly

## Work graph

1. Inventory every live SQLite reader/writer and map it to a Postgres table or adapter.
2. Build a shared DB access layer so new code defaults to Postgres and legacy SQLite is explicit fallback.
3. Migrate scanner/alpha/report/recommendation/paper-ledger consumers to Postgres primary with idempotent dual-read/dual-write where needed.
4. Update cron context wrappers to use Postgres-first helpers and emit stale/fallback warnings when SQLite is used.
5. Run end-to-end dry run: scanner freshness -> alpha handoff -> setup/recommendation path -> Sentinel/Yang reviews -> paper/accountability loop -> report context.
6. Clerky owns board hygiene and role alignment: dependencies, blocked-card review, and ensuring Mike/Clerky/Yang/default are not stepping on each other.

## Agent role adjustment

Current alignment is mostly correct but not fully optimized:

- Mike: Postgres/infrastructure/runtime/usage/storage. Good fit for migration inventory, schema, and safety checks.
- Clerky: board/coordination/status/dependency cleanup. Needs an explicit Postgres migration board-hygiene card.
- Yang: technical entry/exit analysis. Should consume Postgres setups/signals/reviews rather than SQLite recommendation rows once migrated.
- Default/Wolfy/Jonah/Sentinel implementation currently overloaded. Until a dedicated Jonah profile exists, default remains code/market-pipeline implementer, but cards should separate research, implementation, review, and ops responsibilities clearly.

## Verification standard

Every card must report exact commands and outputs. Minimum checks:

```bash
/root/.hermes/wolfy/check_postgres_requirements.py
python3 -m pytest -q /root/.hermes/wolfy
hermes --profile default cron list --all
hermes kanban stats
```

Postgres parity checks should include table counts and recent rows for migrated tables. SQLite fallback checks should explicitly list remaining direct `sqlite3` consumers.
