# Wolfy/Jonah/Sentinel Postgres + Vector Search Scale-Up

Created: 2026-05-31

## Current decision

SQLite remains the live system of record for the existing Wolfy jobs during the transition. PostgreSQL is installed now as the scale-up target and vector-search foundation.

## Installed foundation

- PostgreSQL: 16.14
- Database: `wolfy`
- Local roles: `wolfy`, `root`
- Extensions enabled:
  - `vector` 0.6.0
  - `pg_trgm` 1.6
- Init SQL: `/root/.hermes/wolfy/postgres_init.sql`
- SQLite sync script: `/root/.hermes/wolfy/sync_sqlite_to_postgres.py`

## Postgres coordination/search tables

- `agent_tasks` — task claiming, deduplication, topic/ticker ownership.
- `agent_runs` — per-agent run ledger, future token/cost accounting.
- `agent_artifacts` — durable Jonah/Wolfy/Sentinel outputs.
- `knowledge_chunks` — chunked searchable content with optional `vector(1536)` embedding.
- `recommendation_reviews` — Sentinel challenge/review records.

## Current sync status

Existing SQLite knowledge notes and strategy rules were synced into Postgres as artifacts and chunks. SQLite is still authoritative until job scripts are updated to write both stores or Postgres becomes primary.

## Vector-search plan

Phase 1: lexical search now
- Use `ILIKE`, trigram (`pg_trgm`), tags, and source fingerprints.
- This already helps prevent duplicate research and lets agents find prior work.

Phase 2: embedding queue
- Implemented `/root/.hermes/wolfy/embed_knowledge_chunks.py` and cron wrapper `/root/.hermes/scripts/wolfy_embed_knowledge_chunks.py`.
- Default/fallback method is `local_hashing_vector_v1`: deterministic local 1536-dimensional lexical vectors requiring no paid embedding API.
- When configured, semantic embeddings are available through the OpenAI embeddings API while preserving the `vector(1536)` table contract. Set `OPENAI_API_KEY` and optionally `WOLFY_EMBEDDING_PROVIDER=openai` / `WOLFY_EMBEDDING_MODEL=text-embedding-3-small`.
- Embedding metadata records provider, model, method, and dimensions. Provider/model changes automatically select stale chunks for re-embedding; `--reembed-all` forces replacement.
- Retrieval smoke test: `python3 /root/.hermes/wolfy/embed_knowledge_chunks.py --provider local --limit 0 --smoke-test "risk managed swing trading"` compares vector retrieval against trigram retrieval.
- Cron job `Wolfy Postgres knowledge embedding sync` runs every 30 minutes, no-agent/local, silent unless it errors.

Phase 3: retrieval in agent prompts
- Jonah context now syncs SQLite knowledge into Postgres and prints prior related artifacts before researching to reduce duplicates.
- Wolfy report prompt now logs actionable ideas as `pending_review`; Wolfy does not approve its own recommendations.
- Sentinel context/review job runs after Wolfy reports and reviews pending recommendations against user constraints.

## Cadence decision

- Jonah now runs every 15 minutes.
- Wolfy stays 8 AM / 8 PM ET.
- Sentinel should run after Wolfy or only when pending recommendations exist.
- Usage-limit watchdog runs every 15 minutes and is silent unless a new quota/rate/credit exhaustion event is detected.

## Safety rule

No live trading execution. For paper trading, only recommendations approved by Sentinel should become candidates.
