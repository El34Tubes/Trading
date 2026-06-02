# Wolfy agentic research desk implementation — 2026-05-31

Session learning for recurring stock-research systems that split research, recommendation, review, and persistence.

## User-approved operating model

The user approved a three-agent split:

- **Jonah** — research/knowledge-base agent. Builds durable knowledge and strategy rules only; does not recommend trades.
- **Wolfy** — analyst/trade recommender. Consumes Jonah research, scanner data, and constraints; proposes trade candidates only when evidence supports them.
- **Sentinel** — adversarial reviewer/risk officer. Challenges Wolfy recommendations for feasibility, user constraints, liquidity, account sizing, PDT risk, stale data, catalyst/earnings risk, and manipulation/government-interference exposure.

Authority chain:

1. Jonah informs.
2. Wolfy recommends.
3. Sentinel approves/rejects/requests revisions.
4. User remains final authority for real-money trading.

## Persistence and oversight pattern

The durable coordination layer should not be freeform chat. Persist each agent's work so agents can avoid duplicate effort and consume each other's findings.

Recommended persisted chain:

```text
Jonah research note
  -> strategy rule
  -> scanner result
  -> Wolfy recommendation pending_review
  -> Sentinel review
  -> paper trade/watchlist status
  -> outcome grading
```

Tables used in this implementation:

- `agent_tasks` — task claiming and deduplication.
- `agent_runs` — per-agent run ledger and future token/cost accounting.
- `agent_artifacts` — durable outputs from Jonah/Wolfy/Sentinel.
- `knowledge_chunks` — searchable chunks with optional `vector(1536)` embeddings.
- `recommendation_reviews` — Sentinel challenge/review decisions.

SQLite remains live source-of-truth until jobs are migrated/dual-written; Postgres is the search/coordination scale-up layer.

## Cadence decisions

Fastest efficient cadence approved by user:

- Jonah: every 15 minutes while usage is available.
- Wolfy: keep at 8 AM / 8 PM ET; do not increase report cadence just because Jonah runs faster.
- Sentinel: run after Wolfy, or only when pending recommendations exist.
- Ledger/status: reduce noisy LLM-driven progress chatter; every 4 hours or script-only is preferred.
- Watchdogs: `no_agent=true`, silent unless thresholds or usage-limit events trigger.

## Usage-limit watchdog pattern

Use a no-agent script watchdog rather than an LLM job for quota/rate/credit exhaustion detection. It should:

- scan Hermes logs for new usage-limit/rate-limit/credit messages,
- keep a state file of already-alerted events,
- print only when a new event appears,
- deliver to the origin chat,
- stay silent on empty stdout.

This preserves tokens and avoids repeated alerts.

## Postgres/vector scale-up pattern

The user approved installing Postgres early for scale-up and vector search. Guardrail:

- PostgreSQL maintenance updates are allowed only within the approved project technical requirements.
- Before package maintenance, run `/root/.hermes/wolfy/check_postgres_requirements.py`.
- Current policy allows PostgreSQL 16-line maintenance and blocks major upgrades without explicit user approval and migration review.
- Do not change the `knowledge_chunks.embedding vector(1536)` assumption without explicit migration review.

Implementation detail from this session:

- Postgres 16 + `pgvector` + `pg_trgm` used as the foundation.
- A local deterministic hashed vector embedding (`local_hashing_vector_v1`) can provide immediate cheap pgvector search/dedupe before paid/semantic embeddings are available.
- Store embedding method/dimensions in chunk metadata so embeddings can be safely re-generated later.

## Important pitfall

Do not let Wolfy approve its own recommendations. Wolfy-created actionable ideas must be `pending_review`; Sentinel is the approval/rejection gate. If required trade-ticket fields are missing, classify as watchlist-only or `needs_revision`, not actionable.
