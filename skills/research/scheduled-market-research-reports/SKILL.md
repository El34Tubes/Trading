---
name: scheduled-market-research-reports
description: Build and operate recurring market/stock research reports with macro regime, fundamentals, technical setups, risk controls, token-saving workflows, and scheduled delivery.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [stocks, trading, market-research, swing-trading, cron, email, token-saving]
---

# Scheduled Market Research Reports

Use this skill when a user asks Hermes to become a recurring stock-market analyst, build a trading/investing research system, generate daily recommendations/watchlists, or schedule market reports via email/Discord/cron.

## Core principles

1. Do not promise profitability. Frame outputs as research, decision support, and model development, not guaranteed financial advice.
2. Ask only for constraints that materially change the system: market universe, horizon, risk limits, instruments, timezone, delivery target, data sources, and automation boundaries.
3. Start with a defensible process before individual tickers: macro regime -> universe screen -> fundamental filter -> technical setup -> risk/position sizing -> report.
4. Backtest and/or paper trade before live automation. Never jump directly from a narrative strategy to live trading.
5. Save tokens by using structured data/scripts and cached notes first; use LLM reasoning only for synthesis, exceptions, ranking, and explanation.

## Discovery checklist

Collect or infer these before scheduling durable jobs:

- Market scope: U.S. only, ETFs allowed, ADRs/international allowed, exclusions.
- Instrument scope: stocks only, ETFs, options, shorts, leveraged/inverse ETFs.
- Style/horizon: intraday, swing, position, long-term, or mixed buckets.
- Risk profile: conservative/moderate/aggressive, max drawdown, max position %, number of positions, stop style.
- Liquidity constraints: minimum market cap, average volume, price floor, spread tolerance.
- Account constraints: taxable/retirement, PDT restrictions, approximate account size band.
- Data sources: free/public vs provider APIs such as Polygon, Tiingo, FMP, Alpha Vantage, IEX, broker API.
- Delivery: email, Discord, local file, or multiple targets.
- Schedule/timezone: pre-market, after-close, twice daily, weekdays only, etc.
- Automation boundary: alerts only, human approval, paper trading, or live trading later.

## Research architecture

### 1. Macro regime

Track:

- Index trend and breadth: SPY, QQQ, IWM, DIA; 20/50/200-day structure; advance/decline if available.
- Rates/liquidity: Treasury yields, yield curve, Fed expectations when available.
- Volatility/risk: VIX, credit spreads if available, drawdown state.
- Dollar/commodities: DXY proxy, oil, gold, sector impacts.
- Sector rotation: XLK, XLF, XLY, XLI, XLE, XLV, XLP, XLU, XLB, XLRE, XLC.

Classify environment as risk-on, risk-off, choppy/range-bound, inflation-sensitive, defensive, or narrow-leadership.

### 2. Universe segmentation

Maintain separate screens for:

- Large caps: higher liquidity, institutional leadership, earnings quality.
- Mid caps: growth/valuation dislocations and emerging leaders.
- Small caps: only if liquidity and manipulation-risk constraints pass.
- ETFs: sector/theme/index proxies, useful when individual-stock risk is unattractive.

Avoid low-float, thinly traded, promotional, or regulatory/geopolitical manipulation-prone names unless the user explicitly wants speculative trading.

### 3. Fundamental filter

Score where data is available:

- Revenue and EPS growth.
- Margin trend and free cash flow quality.
- Balance sheet leverage/liquidity.
- Valuation relative to growth and industry.
- Earnings revisions/surprises.
- Competitive quality/moat signals.
- Insider/institutional ownership if available.

### 4. Technical setup

Swing-trading defaults:

- Trend: price vs 20/50/200-day moving averages.
- Relative strength vs SPY and sector ETF.
- Setup: breakout, pullback to rising MA, volatility contraction, base breakout, reclaim, or mean-reversion only in supportive regime.
- Confirmation: volume expansion, close above trigger, market breadth confirmation.
- Risk: ATR-based stop, invalidation level, target/risk-reward, trailing exit.

### 5. Risk and portfolio controls

Every actionable candidate should include:

- Entry zone or trigger.
- Invalidation/stop.
- Initial target or target logic.
- Risk/reward estimate.
- Position-size guidance as a percent-risk concept, not personalized order size unless account constraints are provided.
- Correlation/sector concentration warning.
- Confidence rating and what would change the thesis.

## Report template

Use a concise recurring structure:

1. Macro regime snapshot.
2. Market/sector leadership.
3. Large-cap opportunities.
4. Mid-cap opportunities.
5. Small-cap or ETF opportunities.
6. Watchlist table: ticker, thesis, setup, trigger, stop/invalidation, target/management, confidence.
7. Changes since last report.
8. Model-learning/progress note.
9. Risk disclaimer and next verification steps.

### Tabular formatting preference

For this user's Wolfy reports, use Markdown tables anywhere comparison, ranking, status, or trade-level data is clearer than prose. This is especially useful for scanner/lead rankings, pending recommendations, account/risk controls, Sentinel decisions, Yang technical levels, and Clerky/Kanban/DB status snapshots. Keep narrative short below each table.

Default trade-candidate columns:

`Ticker | Setup/Thesis | Catalyst/Evidence | Entry/Trigger | Stop/Invalidation | Target/Exit | Risk Notes | Status`

Reviewer/technical variants:

- Sentinel: `ID | Ticker | Decision | Required Modification | Max Risk | Key Risk Flags | Reason`
- Yang: `ID | Ticker | Technical Status | Entry/Trigger | Stop | Target/Exit | R Multiple | Note`

Do not force every paragraph into a table; use tables where they improve legibility.

## Token-saving workflow

- Use scripts/API calls to collect raw prices, fundamentals, calendars, and breadth data.
- Store daily snapshots and only send deltas to the LLM.
- Keep a persistent watchlist; refresh changed variables instead of re-researching every name.
- Batch source extraction and summarize into compact JSON/CSV before synthesis.
- Use weekly deep research and daily lightweight updates.
- Keep final reports templated and compact unless anomalies require deeper discussion.

## User-specific Wolfy operating mode

When this user asks for recurring stock reports, load this skill and use the Wolfy operating profile unless superseded in-session:

- Persona/name: Wolfy.
- Tone: direct professional stock-broker voice; cut through corporate noise without over-explaining.
- Universe: U.S. stocks and ETFs first; only consider international exposure if fraud/manipulation/government-interference risk is clearly low.
- Tradability: Robinhood-tradable only.
- Instruments: long-only equities/ETFs; no shorts; options allowed, preferably defined-risk structures during paper trading.
- Portfolio constraints: $5,000 starting paper account, max 3 concurrent positions, stops/invalidation required, and avoid trade frequency that risks Pattern Day Trader limits.
- Objective: seek alpha, but validate through paper trading/backtesting before live automation.

For actionable setups under these constraints, include position sizing suitable for a small paper account, stop/invalidation, holding-period expectation, and whether the idea is a trade candidate or watch-only.

## Agentic team pattern

For larger builds, structure the work as an agentic research desk rather than one monolithic prompt. Prefer a **pipeline with shared state** over multiple loosely coordinated chatbots.

Recommended user-specific split for Wolfy:

- **Jonah — Research Agent:** builds and maintains the knowledge base; processes public/legal or user-provided research; writes notes, rules, source/task status, and durable artifacts. Jonah must not make trade recommendations.
- **Wolfy — Analyst / Trade Recommender:** consumes Jonah's knowledge, scanner results, market context, and user constraints to propose trade candidates with thesis, entry, stop, target, sizing, and status. Wolfy should mark actionable ideas `pending_review` until challenged.
- **Sentinel — Reviewer / Challenger / Risk Officer:** reviews Wolfy's pending recommendations for feasibility, user-constraint compliance, liquidity, sizing, earnings/catalyst risk, stale data, Robinhood tradability, PDT/account constraints, and manipulation/government-interference exposure. Sentinel can approve, reject, or request modification.

Authority chain:

1. Jonah informs.
2. Wolfy recommends.
3. Sentinel approves/rejects/modifies.
4. User remains final authority for real-money trades; only Sentinel-approved candidates should be used for paper-trade candidates.

Keep Jonah mostly silent except for meaningful learning, blockers, or summaries. Keep Wolfy as the primary user-facing market voice. Keep Sentinel terse and adversarial: decision, reason, required modification.

Older role names may still be useful as embedded specialists inside Jonah/Wolfy/Sentinel:

- Macro Scout: rates, index trend, volatility, sector rotation, breadth.
- Fundamental Bloodhound: filings, quality, valuation, dilution/fraud risk.
- Tape Reader: technical setups, relative strength, volume, ATR risk.
- Options Sniper: defined-risk options structures, liquidity, IV/event risk.
- Risk Boss/Sentinel: max positions, stops, PDT constraints, correlation, sizing.
- Data Engineer: free/paid data ingestion, cache, backtests, paper ledger.
- Skeptic/Fraud Filter: manipulation, pump-and-dump, foreign/government-interference risks.
- Report Editor: turns raw research into concise Wolfy reports.

Split into durable cron jobs only when each role writes structured state the others can inspect; otherwise embedded roles in one job are safer and cheaper.

## Usage tracking and cadence tuning

When the user asks whether LLM usage limits are being hit or whether to increase cadence:

1. Check actual usage and failures before recommending changes:
   - `hermes insights --days 1` for sessions/tool calls/tokens by platform/model.
   - Cron job statuses for success/failure and next runs.
   - Hermes logs for quota/rate-limit/429/credit/exhaustion warnings.
2. Distinguish total Hermes usage from cron/agent usage. Cron tokens are the relevant budget for autonomous jobs.
3. Prefer shifting tokens from low-value status chatter into Jonah/research work before increasing all jobs.
4. Add or keep a `no_agent=True` usage-limit watchdog that emits only on new quota/rate/credit events; avoid an LLM-driven watchdog for limit detection.
5. Track per-agent usage in `agent_runs` when available: agent name, job id, status, input/output/total tokens, estimated cost, rows created, and blockers. For Wolfy's Postgres-backed desk, sync Hermes cron sessions from `~/.hermes/state.db.sessions` into `agent_runs` by parsing `cron_<job_id>_<timestamp>` session IDs, joining job names from `hermes --profile default cron list --all`, and upserting by `session_id`; see `references/wolfy-cron-usage-agent-runs-sync-2026-05-31.md`.
6. Keep usage accounting/watchdog jobs script-only and quiet: capture helper stdout so normal runs emit nothing; only print when thresholds, quota/rate-limit events, or actual errors require user attention.
7. If a limit triggers, alert the user and recommend: pause or reduce Jonah cadence, keep script-only watchdogs running, wait for provider reset, or switch model/provider if configured. Record zero-token analytical cron sessions as blocked usage-limit/startup evidence rather than claiming the underlying market-analysis scripts are broken.

Cadence rule of thumb for this user:

- Jonah: fastest useful lever; can run every 15 minutes when usage is available and dedupe/task-claiming exists or is being built.
- Wolfy: keep at 8 AM / 8 PM ET until paper-trade/recommendation logging and intraday data justify more.
- Sentinel: run only after Wolfy or pending recommendations.
- Ledger/status: reduce frequency or make script-only when it becomes noisy.

## Hermes scheduling and delivery

For durable recurring jobs, use the cronjob tool rather than ad-hoc background processes.

- Jobs must have self-contained prompts because cron runs in a fresh context.
- Include the user’s market scope, risk constraints, delivery target, timezone, and disclaimers in the prompt.
- Restrict toolsets when possible, e.g. web/search/terminal/file/messaging depending on the data path.
- If emailing via Hermes gateway, verify Email shows configured before creating jobs that deliver only to email.
- If email is not configured, offer Discord or local report delivery as a temporary fallback.
- If the user asks for Eastern time, prefer `America/New_York` language in prompts and verify how the scheduler stores/renders next-run timestamps. Some cron listings display UTC even after the VPS timezone is set; confirm the actual next run aligns with 8 AM/8 PM Eastern and revisit when DST changes.

Hermes email gateway requires, at minimum:

- `EMAIL_ADDRESS`
- `EMAIL_PASSWORD` or app password
- `EMAIL_IMAP_HOST`
- `EMAIL_SMTP_HOST`

Common Gmail host settings:

- `EMAIL_IMAP_HOST=imap.gmail.com`
- `EMAIL_IMAP_PORT=993`
- `EMAIL_SMTP_HOST=smtp.gmail.com`
- `EMAIL_SMTP_PORT=587`

Do not ask for or print normal mailbox passwords. Prefer app passwords or OAuth-backed platform tooling where available.

## Progress audits and knowledge-base honesty

When the user asks what Wolfy did overnight or whether the knowledge base was updated:

1. Inspect scheduled-job outputs, cron status, and session history before answering; do not rely on memory or assumptions.
2. Report activity by hour in the user's timezone when possible, separating infrastructure/status checks from actual research/model improvements.
3. Be explicit about what did **not** happen. If no books, PDFs, filings, or materials were ingested, say so plainly instead of implying learning occurred.
4. Distinguish durable learning artifacts from ordinary reports:
   - Durable artifacts: scanner scripts, cached datasets, paper ledgers, knowledge-base notes, references files, strategy documents.
   - Non-durable artifacts: a one-off market brief, a cron status message, or a watchlist generated from current bars.
5. If a knowledge-base gap is discovered, make the next build step concrete: create a structured knowledge base, ingest cited materials, and connect those principles to scanner/report logic.

## Wolfy durable DB workflow

For this user's Wolfy setup, use `/root/.hermes/wolfy/wolfy.db` as the local SQLite source of truth. The installed SQLite CLI is available as `sqlite3`; Python's `sqlite3` module is also available.

Core files:

- `/root/.hermes/wolfy/wolfy.db` — SQLite database.
- `/root/.hermes/wolfy/init_wolfy_db.py` — schema + seed curriculum/tasks/allowlist.
- `/root/.hermes/wolfy/sources/inbox/` — user-provided source-file drop zone for semi-structured material before DB persistence.
- `/root/.hermes/wolfy/queue_knowledge_source_files.py` — queues inbox files into SQLite `knowledge_sources` with `url_or_reference` pointing to the absolute file path.
- `/root/.hermes/wolfy/wolfy_scanner.py` — Yahoo-chart free-data scanner; writes `scanner_runs` and `scanner_results`.
- `/root/.hermes/wolfy/hourly_knowledge_context.py` — picks the next source/task for hourly knowledge-building; for existing absolute local file paths, instructs Jonah to read the file directly before distilling notes/rules.
- `/root/.hermes/wolfy/wolfy_status.py` — DB/storage/table-count status; writes `system_metrics`.
- `/root/.hermes/wolfy/wolfy_storage_watchdog.py` — silent watchdog; records metrics and only emits alerts above thresholds.
- `/root/.hermes/wolfy/TRAINING_PLAN.md` — autonomous curriculum, tracking, and scale-up plan.

Key tables:

- `knowledge_sources`, `knowledge_notes`, `strategy_rules`, `training_tasks` for learning.
- `scanner_runs`, `scanner_results`, `market_snapshots` for data/scanner history.
- `reports`, `recommendations`, `paper_trades`, `recommendation_outcomes` for accountability.
- `system_metrics`, `automation_allowlist` for operations.

Cron jobs currently used:

- Wolfy twice-daily stock research report — 8 AM / 8 PM ET equivalent schedule, Discord delivery.
- Wolfy/Clerky four-hour activity ledger — every 4 hours, Discord/origin delivery; summarizes activity instead of reporting every Jonah run. Use a deterministic pre-run context script (`wolfy_clerky_activity_context.py`) for schema-sensitive admin facts instead of making the LLM rediscover Kanban/Postgres schemas; see `references/wolfy-clerky-deterministic-ledger-context-2026-06-01.md`.
- Jonah 20-minute autonomous knowledge builder — every 20 minutes, local delivery only, uses `wolfy_hourly_knowledge_context.py` wrapper under `~/.hermes/scripts/`. Jonah's prompt should focus on research/knowledge insertion and avoid trade recommendations; do not spam the user with every Jonah run.
- Wolfy storage watchdog — :30 each hour, `no_agent=True`, silent unless thresholds trip, uses `wolfy_storage_watchdog.py` wrapper under `~/.hermes/scripts/`.
- Wolfy LLM usage-limit watchdog — every 15 minutes, `no_agent=True`, silent unless new quota/rate-limit/credit-exhaustion events appear in Hermes logs, uses `/root/.hermes/scripts/wolfy_usage_limit_watchdog.py`.
- Mike autonomous environment repair loop may run under the Mike profile even though the Wolfy production cron jobs live under the default profile. For audits, check `hermes --profile default cron list --all` in addition to the active profile before concluding there are no jobs.

Cadence guidance:

- If the user wants fastest build speed and usage limits are not tripping, increase Jonah first; research is the compounding asset.
- Do not increase Wolfy report cadence just because Jonah cadence increases; Wolfy should run at decision times unless intraday data/paper-trade logic exists.
- Run Sentinel after Wolfy or only when pending recommendations exist; avoid hourly review jobs that review nothing.
- Watchdog jobs should be `no_agent=True` and silent on empty stdout to preserve tokens.

### User-provided source-file inbox

When the user asks where to add semi-structured materials before database persistence, point them to the filesystem inbox first, not only SQL tables:

```bash
/root/.hermes/wolfy/sources/inbox/
cd /root/.hermes/wolfy
python3 queue_knowledge_source_files.py
```

Accepted file types are `.md`, `.txt`, `.csv`, `.json`, `.yaml`, and `.yml`. Optional sibling sidecars named `<basename>.source.json` can specify title, author, source_type, access_mode, copyright_status, priority, and quality_score. The queue script inserts rows into `knowledge_sources` and stores the absolute local file path in `url_or_reference`; Jonah should then read that file directly and persist distilled `knowledge_notes` / `strategy_rules`. See `references/wolfy-source-file-inbox-2026-06-01.md` for the exact session implementation and sidecar example.

Honesty rule: Wolfy may only claim durable learning if it inserted `knowledge_notes` and/or `strategy_rules` into `wolfy.db`, and it must distinguish public/framework-level learning from user-provided book/material ingestion.

Scale-up thresholds and current scale-up foundation:

- SQLite remains the current live source of truth until job scripts are migrated or dual-written.
- Postgres scale-up foundation is installed for this user: database `wolfy`, PostgreSQL 16, `pgvector`, and `pg_trgm`.
- DB >1GB: optimize/archive/index review.
- DB >5GB or multiple concurrent writer contention: migrate live writes from SQLite to Postgres.
- Wolfy dir >20GB: move raw artifacts to object storage/compressed archives.
- Root disk >70%: prune/archive logs, back up DB off-disk, expand volume.
- Semantic search over large notes: use Postgres `knowledge_chunks` with `pg_trgm` now and `pgvector` embeddings once an embedding-generation script is added.

Postgres/vector files for this user:

- `/root/.hermes/wolfy/postgres_init.sql` — schema for `agent_tasks`, `agent_runs`, `agent_artifacts`, `knowledge_chunks`, and `recommendation_reviews`.
- `/root/.hermes/wolfy/sync_sqlite_to_postgres.py` — syncs existing SQLite knowledge notes and strategy rules into Postgres search/coordination tables.
- `/root/.hermes/wolfy/POSTGRES_VECTOR_SCALEUP.md` — scale-up handoff notes.
- `/root/.hermes/wolfy/postgres_requirements.json` — durable guardrails for allowed PostgreSQL/pgvector versions and blocked destructive changes.
- `/root/.hermes/wolfy/check_postgres_requirements.py` — run this before Postgres package maintenance; it verifies current/candidate versions remain within Wolfy's technical requirements.

Guarded Postgres maintenance rule:

- The user permits Postgres maintenance/update automation, but updates must be guarded against exceeding the project's technical requirements.
- Before any Postgres update, run `/root/.hermes/wolfy/check_postgres_requirements.py` and inspect apt candidates with `apt-cache policy postgresql postgresql-16 postgresql-16-pgvector`.
- Allowed maintenance pattern is PostgreSQL 16-line security/patch updates only, e.g. `apt-get install --only-upgrade postgresql postgresql-16 postgresql-contrib postgresql-16-pgvector postgresql-client-16 postgresql-client-common postgresql-common`.
- Do not upgrade to PostgreSQL 17+ or change `knowledge_chunks.embedding vector(1536)` / pgvector assumptions without explicit user approval and a migration review.
- Never drop/recreate the `wolfy` database or run destructive migrations as routine maintenance.

Multi-agent persistence pattern:

- `agent_tasks`: task claiming, deduplication, topic/ticker ownership, source fingerprints.
- `agent_runs`: per-agent run ledger and future token/cost accounting. For cron-backed rows, prefer one idempotent row per Hermes cron session with `session_id`, `cron_job_id`, `source='cron'`, token/cache/message/tool counters, and a `blocked` status for zero-token analytical runs caused by usage limits or startup failure.
- `agent_artifacts`: durable outputs from Jonah/Wolfy/Sentinel.
- `knowledge_chunks`: chunked searchable content with optional `vector(1536)` embeddings.
- `recommendation_reviews`: Sentinel's challenge/review decisions.

Operational helper files now installed under `/root/.hermes/wolfy/`:

- `wolfy_agent_coordination.py` — Python helper API for `agent_runs` and `agent_tasks` (`ensure_agent_task`, `claim_next_task`, `start_agent_run`, `finish_agent_run`, etc.).
- `wolfy_agent_cli.py` — cron/agent-friendly CLI bridge. Use `run-start`, `run-finish`, `task-ensure`, `task-claim`, `complete`, and `block` so autonomous jobs leave durable Postgres run/task state.
- `test_agent_coordination_smoke.py` — smoke tests proving rows insert and duplicate task claiming is avoided.
- `sync_cron_usage_to_agent_runs.py` — idempotently syncs Hermes cron sessions from `~/.hermes/state.db` into Postgres `agent_runs` for per-agent usage accounting; keep wrappers under global/Mike/Clerky `scripts/` synchronized when profile cron jobs call it.
- `wolfy_clerky_activity_context.py` — deterministic pre-run context for Clerky's four-hour administrative ledger. It should own schema-sensitive reads of Kanban SQLite, Wolfy SQLite, Hermes state, and Postgres coordination ledgers so Clerky summarizes facts instead of guessing table/column names.

Use this chain for auditable trade ideas: Jonah research note -> strategy rule -> scanner result -> Wolfy recommendation -> Sentinel review -> paper trade/watchlist status -> outcome grading.

Scanner acceleration pattern for this user: when asked to "get more in there sooner," improve deterministic coverage before increasing LLM work. Add/refresh a liquid U.S. universe cache, compute volume/breakout/squeeze/relative-strength/liquidity factors, run script-only intraday scanner snapshots, and auto-create structured alpha-lead handoffs from top anomalies. Treat scanner outputs as leads, not recommendations, until they pass promotion, Sentinel, Yang/technical review, and paper-ledger gates. A scanner freshness gate should run before decision reports; stale data means no actionable recommendation.

## Implementation Kanban acceleration

When this user asks to "Kanban" Wolfy build priorities and complete them without prompting, act as an implementation orchestrator, not just an analyst:

1. Inspect the current Wolfy board and cron state before creating cards, so existing blocked/todo cards are reused instead of duplicated.
2. If a card is blocked only for review and has a worker handoff, rerun the cited verification commands. If they pass, comment with the real output and complete/unblock it so downstream dependencies can move.
3. Create dependency-linked cards for the accountability loop rather than flat independent tasks: scanner freshness -> lead promotion -> report integration; recommendation logger -> Sentinel persistence -> paper portfolio/outcomes; then an end-to-end smoke/cron handoff card depending on both lanes.
4. Save a durable project plan in `/root/.hermes/wolfy/` and reference it from the cards.
5. Comment on active cards that routine code/test/schema-compatible implementation should proceed autonomously; workers should block only for destructive DB/package changes, paid credentials/APIs, broker/live-trading authority, or legal/data-access blockers.
6. Run `hermes kanban dispatch` after creating/updating cards so execution actually starts.

See `references/wolfy-accountability-loop-kanban-plan-2026-06-01.md` for the concrete dependency graph and verification pattern from the accountability-loop implementation push.

## References

- `references/user-stock-research-preferences.md` — session-specific preferences captured from the first stock-research automation setup conversation.
- `references/wolfy-overnight-audit-2026-05-31.md` — first overnight audit details: what actually ran, what artifacts were created, and the confirmed gap that book/material ingestion had not yet happened.
- `references/wolfy-multi-agent-postgres-scaleup-2026-05-31.md` — Jonah/Wolfy/Sentinel split, inter-agent persistence pattern, Jonah cadence change, usage-limit watchdog, and Postgres/pgvector scale-up details.
- `references/wolfy-agentic-research-desk-implementation-2026-05-31.md` — final implementation pattern for the three-agent desk: persisted oversight chain, 15-minute Jonah cadence, Sentinel post-Wolfy gatekeeping, quiet usage-limit watchdog, guarded Postgres maintenance, and local hashed pgvector embeddings.
- `references/wolfy-alpha-yang-kanban-postgres-helper-2026-05-31.md` — alpha module additions from a YouTube-inspired request, Yang technical-analysis agent pattern, bounded Kanban allocator pattern, and the Postgres helper `block_task()` psycopg type-cast fix.
- `references/wolfy-cron-usage-agent-runs-sync-2026-05-31.md` — Mike ops pattern for syncing Hermes cron session token counters into Postgres `agent_runs`, keeping script-only usage snapshots quiet, and preserving a legacy alpha-search wrapper path.
- `references/wolfy-mike-autonomous-env-triage-2026-06-01.md` — Mike autonomous triage pattern: verify default-profile cron from a Mike run, run deterministic smoke tests/autorepair, interpret silent helpers correctly, and avoid treating the current `agent_runs.status='started'` row as stale.
- `references/wolfy-mike-runtime-triage-2026-06-01.md` — Mike runtime repair detail: install optional imports into the Hermes venv, preserve legacy alpha-search wrapper paths, sync profile wrappers, and verify with smoke tests plus script-only helpers.
- `references/wolfy-mike-triage-default-cron-context-2026-06-01.md` — Mike triage-script pitfall/fix: include default-profile production cron status alongside the active Mike profile's empty cron list so future ops runs do not falsely report no scheduled jobs.
- `references/wolfy-paper-trades-compatibility-aliases-2026-06-01.md` — Mike repair pattern for non-destructive `paper_trades` compatibility aliases (`qty`, `opened_at`, `closed_at`), alias triggers, and smoke-test cleanup when Wolfy report diagnostics use common trade-ledger column names.
- `references/wolfy-embedding-legacy-wrapper-autorepair-2026-06-01.md` — Mike repair pattern for preserving renamed script compatibility (`wolfy_embed_knowledge_chunks.py` → `embed_knowledge_chunks.py`), teaching `mike_safe_autorepair.py` to recreate the wrapper, and verifying no-agent helpers remain silently healthy.
- `references/wolfy-wrapper-autorepair-global-profile-sync-2026-06-01.md` — follow-up nuance: verify and sync all invocation layers for renamed scripts (live Wolfy implementation, Wolfy legacy wrapper, global `/root/.hermes/scripts/` wrapper, and profile script wrappers), because default-profile cron can call the global wrapper even when a profile wrapper is healthy.
- `references/wolfy-report-tables-scanner-scaleup-2026-06-01.md` — report-format and scanner scale-up pattern: Markdown tables for legible Wolfy/Sentinel/Yang/Clerky outputs, scanner freshness gates, broader liquid universe, deterministic factors, intraday no-agent snapshots, and alpha-lead handoffs before recommendations.
- `references/wolfy-source-file-inbox-2026-06-01.md` — source-file inbox pattern for user-provided semi-structured material: drop files under `/root/.hermes/wolfy/sources/inbox/`, queue with `queue_knowledge_source_files.py`, optional `.source.json` sidecars, and Jonah local-file reading instruction.
