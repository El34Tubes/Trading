# Wolfy multi-agent/Postgres scale-up session notes — 2026-05-31

## What changed

The user chose to split the Wolfy system into three durable roles:

- **Jonah** — research agent. Builds the knowledge base from public/legal or user-provided material. Writes notes/rules/tasks. Does not recommend trades.
- **Wolfy** — analyst and trade recommender. Consumes Jonah research, scanner results, and user constraints. Produces trade candidates, initially `pending_review`.
- **Sentinel** — reviewer/challenger/risk officer. Approves/rejects/requests modification based on feasibility, risk, account constraints, Robinhood tradability, liquidity, stale data, and manipulation/geopolitical exposure.

The user explicitly wanted persistent inter-agent oversight so agents do not duplicate work and can use each other's findings.

## Architecture lesson

Prefer a **pipeline with shared database state** over several chatbots freely debating.

Auditable chain:

`Jonah research note -> strategy rule -> scanner result -> Wolfy recommendation -> Sentinel review -> paper trade/watchlist -> outcome grading`

Important tables/patterns:

- `agent_tasks` for task claiming, dedupe, topic/ticker ownership, source fingerprints.
- `agent_runs` for per-agent run history and future token/cost accounting.
- `agent_artifacts` for durable outputs.
- `knowledge_chunks` for text/vector retrieval.
- `recommendation_reviews` for Sentinel decisions.

## Cadence lesson

When usage limits are not tripping, increase **Jonah** first because research compounds. Do not automatically increase Wolfy or Sentinel:

- Jonah: every 15 minutes if the user wants maximum build speed.
- Wolfy: 8 AM / 8 PM ET until intraday/paper-trade systems justify more.
- Sentinel: after Wolfy or when `pending_review` recommendations exist.
- Ledger/status: make script-only or reduce frequency if it burns tokens on chatter.

## Usage-limit monitoring lesson

Use a `no_agent=True` watchdog that scans Hermes logs for new quota/rate-limit/credit/exhaustion events and emits only on change. Avoid LLM-driven monitoring for usage limits.

## Postgres/vector scale-up state

Postgres was installed as the future scale-up target while SQLite remains current source of truth.

Installed foundation:

- PostgreSQL 16 database: `wolfy`
- Extensions: `vector` 0.6.0, `pg_trgm` 1.6
- Init SQL: `/root/.hermes/wolfy/postgres_init.sql`
- Sync script: `/root/.hermes/wolfy/sync_sqlite_to_postgres.py`
- Scale-up notes: `/root/.hermes/wolfy/POSTGRES_VECTOR_SCALEUP.md`
- Requirements guard: `/root/.hermes/wolfy/postgres_requirements.json`
- Pre-update guard script: `/root/.hermes/wolfy/check_postgres_requirements.py`

Initial sync inserted existing SQLite `knowledge_notes` and `strategy_rules` into Postgres `agent_artifacts` and `knowledge_chunks`. Real embeddings still require an embedding-generation script/provider; pgvector schema and index are ready.

## Guarded Postgres maintenance lesson

The user explicitly allows Postgres to be on the permanent Wolfy allowlist for updates, but only if updates are checked against the project's technical requirements first.

Operational pattern:

1. Run `/root/.hermes/wolfy/check_postgres_requirements.py` before Postgres maintenance.
2. Inspect candidates with `apt-cache policy postgresql postgresql-16 postgresql-16-pgvector`.
3. Only apply maintenance/security upgrades within the PostgreSQL 16 line, using `apt-get install --only-upgrade ...` for the approved Postgres packages.
4. Treat PostgreSQL 17+, embedding dimension changes, pgvector schema/index changes, or destructive DB migrations as blocked until the user explicitly approves a migration review.

## Pitfalls

- Do not let Jonah recommend trades; it contaminates the research role.
- Do not let Wolfy self-approve recommendations; Sentinel must challenge them.
- Do not claim book/material ingestion unless notes/rules were actually inserted from public/legal or user-provided material.
- Do not increase report/status jobs when the real bottleneck is knowledge growth.
- Do not treat package-update permission as permission for major Postgres upgrades or destructive database migrations.
