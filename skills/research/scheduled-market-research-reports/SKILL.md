---
name: scheduled-market-research-reports
description: Build and operate recurring market/stock research reports with macro regime, fundamentals, technical setups, risk controls, token-saving workflows, and scheduled delivery.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [stocks, trading, market-research, swing-trading, cron, email, token-saving]
    related_skills: [hermes-runtime-operations]
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

- Blue chips: highest-quality liquid leadership names; safest first expansion tier.
- Large caps: higher liquidity, institutional leadership, earnings quality.
- Mid caps: growth/valuation dislocations and emerging leaders.
- Small caps: only if liquidity and manipulation-risk constraints pass.
- ETFs: sector/theme/index proxies, useful when individual-stock risk is unattractive.

Avoid low-float, thinly traded, promotional, or regulatory/geopolitical manipulation-prone names unless the user explicitly wants speculative trading.

For Wolfy EOD expansion, segment and backfill tiers instead of loading one large mixed universe. Prefer a durable selector/backfill shape with `wolfy_tier`, `tier_source`, `backfill_priority`, `backfill_enabled`, `universe_tier_rules`, and `universe_backfill_targets`; load `blue_chip` and `etf_core` before large/mid/small caps, and use small resumable chunks to avoid timeout-before-commit loss. For full remaining-tier pulls, run a background JSONL-logging backfill helper plus a separate PID-waiting post-verifier that recomputes signals and runs targeted tests; report process IDs, log paths, and DB counts rather than implying completion. See `references/wolfy-tiered-universe-backfill-2026-06-26.md` and `references/wolfy-tiered-backfill-runner-and-post-verify-2026-06-27.md`.

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

### Visible progress / “where are we at” status shape

When this user is frustrated about not seeing Wolfy progress, answer with measurable state changes instead of reassurance. Keep it compact and concrete:

- What changed in durable systems: DB rows/date ranges, scripts, tests, strategy statuses, cron/job state.
- What still blocks visible setups: no approved strategy, stale data, failed OOS validation, missing earnings/calendar data, or pending human approval.
- What is in progress next: one implementation target, not a broad roadmap.

Prefer a short table for strategy gates: `Strategy | Status | OOS result | Gate result | Next action`. Under Hermes-EOD, explicitly say `candidate is not approved` when relevant.

See `references/wolfy-eod-historical-depth-and-strategy-gates-2026-06-18.md` for a concrete historical-depth/backfill/strategy-gate audit pattern.

### Interview-style decision gathering preference

When this user asks to resolve Wolfy blockers, optimization choices, recommendation-engine settings, or agentic-loop tradeoffs, use interview-style decision prompts with selectable options one decision at a time. Do not dump a long questionnaire in prose. Record each decision, then proceed to the next meaningful gate. If a user answer conflicts with an existing constraint (for example "10/day" vs max 3 open positions), ask a targeted follow-up to resolve the conflict before encoding it. See `references/wolfy-recommendation-engine-interview-decisions-2026-07-19.md` for the earlier recommendation-engine decision sequence and `references/wolfy-recommendation-engine-interview-and-options-strategy-2026-07-29.md` for the latest options-focused strategy/interview decisions, including the user's correction that options liquidity is informational/user-evaluated rather than a hard gate.

### Tabular formatting preference

For this user's Wolfy reports, use Markdown tables anywhere comparison, ranking, status, or trade-level data is clearer than prose. This is especially useful for scanner/lead rankings, pending recommendations, account/risk controls, Sentinel decisions, Yang technical levels, and Clerky/Kanban/DB status snapshots. Keep narrative short below each table.

Default trade-candidate columns:

`Ticker | Setup/Thesis | Catalyst/Evidence | Entry/Trigger | Stop/Invalidation | Target/Exit | Risk Notes | Status`

Reviewer/technical variants:

- Sentinel: `ID | Ticker | Decision | Required Modification | Max Risk | Key Risk Flags | Reason`
- Yang: `ID | Ticker | Technical Status | Entry/Trigger | Stop | Target/Exit | R Multiple | Note`

Do not force every paragraph into a table; use tables where they improve legibility.

## Mobile command dashboard pattern

When this user asks for phone/mobile visibility across Wolfy/Hermes progress, build a dashboard as a **summary-level command center**, not another verbose report. Default to a Dockerized, platform-agnostic public/VPS-ready web app with PIN protection, 60-second refresh, and a mobile landing page whose first module is a **current point-in-time snapshot**. Do not make history/timeline the default; the user explicitly prefers current state unless they ask for historical drilldown.

Core v1 modules:

- Current snapshot from `agent_tasks`, `agent_runs`, `recommendations`, and `paper_trades`: queued/in-progress/failed tasks, active runs, recommendations needing attention, open paper trades.
- Auto-discovered agents/profiles rather than a fixed Wolfy-only list.
- Recommendations and pending approval/paper-candidate attention from Postgres `recommendations`.
- Paper-trade visibility from `paper_trades`.
- Environment health from `system_metrics`/`loop_metrics` where available.
- Manual notes/status overrides stored separately from trading state.
- Agent/LLM-suggested interview polls that the user can click in the dashboard; poll clicks must POST/write back, and the dashboard should show the latest/current answer per poll rather than accumulating answer history by default.

Implementation guardrails:

- Keep dashboard writes narrow: manual notes/status overrides and poll answers only. Do not let a v1 dashboard mutate strategies, recommendations, paper trades, cron jobs, or live execution state.
- Put secrets/config in environment variables (`WOLFY_DASHBOARD_PIN`, `WOLFY_POSTGRES_DSN`), not code or committed compose files.
- Test real authenticated `/api/summary`; `/healthz` alone is not enough because schema/SQL errors can hide behind a passing health endpoint.
- Query live Postgres schemas conservatively. Do not assume alias columns such as `agent_runs.agent` exist; use actual columns or inspect schema before writing dashboard SQL.

When the dashboard target is a Hostinger VPS, first inspect the existing `/docker/traefik` and `/docker/*/docker-compose.yml` stack before asking for credentials. If Traefik is already serving `*.hstgr.cloud` with Docker labels, you can often deploy immediately under `<service>.<TRAEFIK_HOST>` with a generated PIN in `/docker/<service>/.env`, host networking, and the existing Let's Encrypt resolver. Verify authenticated `/api/summary` over public HTTPS, not just `/healthz`.

See `references/wolfy-mobile-command-dashboard-2026-08-06.md` for the concrete FastAPI/Docker implementation, test shape, smoke verification, public/VPS launch checklist, and deploy commands. See `references/wolfy-hostinger-dashboard-deployment-2026-08-06.md` for the no-human-intervention Hostinger/Traefik deployment pattern. See `references/wolfy-dashboard-current-snapshot-poll-writeback-2026-08-07.md` for the user correction that the dashboard should default to current point-in-time status and that clickable polls must write back as latest/current answers, not history.

## Token-saving workflow

- Use scripts/API calls to collect raw prices, fundamentals, calendars, and breadth data.
- Store daily snapshots and only send deltas to the LLM.
- Keep a persistent watchlist; refresh changed variables instead of re-researching every name.
- Batch source extraction and summarize into compact JSON/CSV before synthesis.
- Use weekly deep research and daily lightweight updates.
- Keep final reports templated and compact unless anomalies require deeper discussion.
- For this user, default to brief bullets/tables, avoid filler sentences, continue working silently when no user decision is needed, challenge weak assumptions, and recommend the strongest forward path instead of neutrally listing every option.

## User-specific Wolfy operating mode

When this user asks for recurring stock reports, load this skill and use the Wolfy operating profile unless superseded in-session:

- Persona/name: Wolfy.
- Tone: direct professional stock-broker voice; cut through corporate noise without over-explaining.
- Universe: U.S. stocks and ETFs first; only consider international exposure if fraud/manipulation/government-interference risk is clearly low.
- Tradability: Robinhood-tradable only.
- Instruments: long-only equities/ETFs; no shorts; options allowed, preferably defined-risk structures during paper trading.
- Portfolio constraints: for the latest paper-recommendation testing mode, use 5% paper risk per trade, no max-open cap, max 3 paper-eligible recommendations per day, stops/invalidation required, and EOD-close baseline entries. Older $5,000 / 1–2% / max-3-open defaults are superseded for this paper-testing workflow, but real-money/live trading remains unapproved.
- Objective: seek alpha, but validate through paper trading/backtesting before live automation.

### Hermes-EOD framework override

If the user references the newer Hermes-EOD goals/constitution/framework, treat it as the governing Wolfy operating mode over the earlier twice-daily swing-report posture:

- **EOD only:** decisions use closing data; any execution is next-session and human-only.
- **LLM out of the signal path:** deterministic scripts/functions compute prices, features, strategy signals, risk checks, and setup eligibility. The LLM interprets, filters, ranks, explains, and writes proposals; it never fabricates or invents numeric edge.
- **No auto-execution:** no broker authority, no money movement, no live order placement.
- **Human-gated strategy deployment:** strategies move `research_only -> candidate -> approved -> retired`; agents may mark `candidate` after walk-forward/setup-outcome validation. For this user's latest Wolfy paper-testing workflow, strategies that pass the current setup-outcome-native gate may auto-activate as `approved` for **paper recommendations only**; this does not grant live trading, broker execution, or money movement.
- **Approved-strategy gate:** actionable setup proposals require deterministic signal rows tied to `strategies.status='approved'`. Research-only/candidate signals can be reported as research/watch-only, not capital setups.
- **Historical-depth gate:** before treating EOD backtests or walk-forward OOS results as meaningful, verify daily OHLCV depth per ticker and date range. Shallow windows (for example ~60-90 days) must be fixed before strategy tuning. For this user's swing/EOD framework, prefer at least ~730 calendar days when the data source supports it, then backfill deterministic features/signals before revalidating.
- **Regression-test ingest defaults:** when a shallow-history ingest default is discovered, add a wrapper-level test asserting the live/default run requests the intended history depth, then patch the wrapper and rerun the test.
- **Candidate is not approved:** walk-forward validation can promote a strategy to `candidate`, but that still cannot generate capital/paper setup proposals until the human explicitly marks it `approved`.
- **Risk circuit breakers are code gates:** enforce risk-per-trade, portfolio heat, max name weight, ADV fraction, drawdown kill switch, slippage/cost assumptions, and event/liquidity exclusions before proposing new risk.
- **Quiet nights are valid:** prefer no setup over forced trades.
- **FACT vs JUDGMENT:** every rationale should distinguish measured/filed/database facts from inference.

Under Hermes-EOD, scanner/social/Alpha Search outputs are candidate-discovery context only until they pass deterministic strategy, screening, risk, and approval gates. See `references/wolfy-hermes-eod-framework-2026-06-01.md` for the session-specific implementation graph and safety boundary.

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
4. Add or keep a `no_agent=True` usage-limit watchdog that emits only on new quota/rate/credit events; avoid an LLM-driven watchdog for limit detection. For this user's current Wolfy setup, `/root/.hermes/scripts/wolfy_usage_limit_watchdog.py` should scope auth checks to the active production model provider (for example `hermes --profile default auth list openai-codex`), not a bare all-provider auth listing that can probe unrelated Copilot/GitHub credentials and create false-positive ops noise. When `usage_limit_reached`/429/rate-limit is active, it auto-pauses LLM-driven Wolfy/Mike cron jobs to stop repeated Discord quota spam while leaving script-only scanners/watchdogs running, then auto-resumes those LLM jobs when the provider limit clears.
5. Track per-agent usage in `agent_runs` when available: agent name, job id, status, input/output/total tokens, estimated cost, rows created, and blockers. For Wolfy's Postgres-backed desk, sync Hermes cron sessions from `~/.hermes/state.db.sessions` into `agent_runs` by parsing `cron_<job_id>_<timestamp>` session IDs, joining job names from `hermes --profile default cron list --all`, and upserting by `session_id`; see `references/wolfy-cron-usage-agent-runs-sync-2026-05-31.md`.
6. Keep usage accounting/watchdog jobs script-only and quiet: capture helper stdout so normal runs emit nothing; only print when thresholds, quota/rate-limit events, or actual errors require user attention.
7. If a limit/429 triggers, report it in the shortest useful form: event + timestamp only (user timezone when possible). Do **not** paste raw error logs, repeated matching lines, stack traces, or usage dashboards unless the user explicitly asks for detail. Then state the operational decision: which jobs remain paused/gated vs which script-only loops continue.
8. Watchdog evidence must be fresh and anchored. Do not let undated historical traceback/payload lines count as today's active limit; trim or rotate stale 429/log evidence rather than repeatedly rescanning old raw payloads; do not echo raw quota-pattern substrings into watchdog output that will be rescanned next tick; reconcile `paused_llm_jobs` against actual cron job enabled/paused state before making claims. If watchdog state says limited but a minimal live provider probe succeeds, treat it as a stale-evidence repair path, not as proof the provider is down. **Do not gate Wolfy/Mike on auxiliary-provider noise**: `agent.auxiliary_client` warnings for OpenRouter/Nous payment/credit errors or compression fallback exhaustion are not production `openai-codex` usage-limit evidence. Scope gating to the active production provider and concrete quota terms (`usage_limit_reached`, `HTTP/status 429`, rate limit, too many requests); direct watchdog runs should be silent when production auth is clear. See `references/wolfy-usage-watchdog-auxiliary-provider-false-positive-2026-07-09.md`.
9. If a limit triggers, alert the user and recommend: pause or reduce Jonah cadence, keep script-only watchdogs running, wait for provider reset, or switch model/provider if configured. Record zero-token analytical cron sessions as blocked usage-limit/startup evidence rather than claiming the underlying market-analysis scripts are broken.
10. For regular GitHub checkpoints, commit source/config/docs/tests only after verification and leave runtime logs, caches, temp JSON, backups, known-good snapshots, and generated state ignored/untracked unless the user explicitly asks to version them. See `references/wolfy-knowledge-chunk-objective-audit-and-log-hygiene-2026-07-09.md` for the stale-429 hygiene and checkpoint report shape.

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

When the user asks what Wolfy did overnight, whether the knowledge base was updated, "where are we at," whether the system is "set up correctly to loop," or signals frustration that they are not seeing progress:

1. Inspect scheduled-job outputs, cron status, session history, and database state before answering; do not rely on memory or assumptions.
2. Split the audit into two layers:
   - **Visible LLM/report layer:** Wolfy, Jonah, Alpha Search, Clerky, Sentinel, Yang, and Mike LLM cron jobs.
   - **Silent script-only backend:** usage/storage watchdogs, embeddings sync, stale cleanup, safe autorepair, intraday scanner snapshots, EOD ingest/features/signals, pre-open monitor, and revalidation jobs.
3. Check the usage-limit watchdog state before concluding work stopped. If LLM jobs are paused due to a now-expired provider/rate limit, run the watchdog/resume path and verify jobs are enabled again before reporting back. If the watchdog is now silent/no active limit but LLM-driven jobs remain paused, explicitly resume the paused user-visible/LLM jobs with the cronjob tool rather than waiting for a future watchdog tick. If the missed job is a visible Wolfy report and the user is asking about today, manually run the report once after resuming it, then verify cron output/delivery before saying it was delivered. If logs show provider/credential exhaustion, report LLM-driven progress as quota-gated while script-only jobs continue, not as a total loop failure.
4. For loop-readiness audits, verify gateway/cron is running, count active vs paused jobs, confirm Postgres requirements, then query operational freshness directly. For Wolfy's EOD price/feature path use Postgres tables `prices`, `features`, and `runs` with date column `dt`; do not query nonexistent `eod_prices`/`eod_features` aliases unless a compatibility view was intentionally added.
5. If EOD ingest timed out under cron, treat it as an ingest-window/rate-limit bottleneck. Prove the API/parser path with a tiny dry-run, check stored max dates/counts, then recommend or implement smaller ticker shards / incremental runs / bounded backfill verification. Do not imply the full ingest completed from a timed-out run. For Wolfy's current core EOD universe, the proven production fix is five no-agent shard wrappers under `/root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_{1..5}.py`, scheduled 16:30/16:35/16:40/16:45/16:50 ET, each calling `/root/.hermes/wolfy/eod_price_features.py --source massive --days 730 --no-validate` with bounded ticker subsets so the run fits under the cron script timeout; keep deterministic signals after the shard window (currently 17:05 ET).
6. Report activity by hour in the user's timezone when possible, separating infrastructure/status checks from actual research/model improvements.
7. Be explicit about what did **not** happen. If no books, PDFs, filings, or materials were ingested, say so plainly instead of implying learning occurred.
8. Distinguish durable learning artifacts from ordinary reports:
   - Durable artifacts: scanner scripts, cached datasets, paper ledgers, knowledge-base notes, references files, strategy documents, Postgres rows for prices/features/signals/tasks/runs.
   - Non-durable artifacts: a one-off market brief, a cron status message, or a watchlist generated from current bars.
9. For Hermes-EOD, treat `0 setups` as a valid gated outcome when strategies are still `research_only` or deterministic/approved-strategy gates block capital ideas. Report `NO SETUP / WATCHLIST ONLY` with the gate reason rather than implying the pipeline failed.
10. If a knowledge-base or visibility gap is discovered, make the next build step concrete: create/repair the structured knowledge base, ingest cited materials, connect principles to scanner/report logic, or add a clearer progress notification.

See `references/wolfy-visible-progress-audit-2026-06-18.md` for the concrete audit/resume sequence from the session where LLM jobs were paused while script-only EOD ingest/signals continued. See `references/wolfy-paused-llm-jobs-manual-resume-and-catchup-report-2026-06-30.md` for the follow-up pattern where the watchdog was silent/no active limit but LLM jobs remained paused: explicitly resume the paused LLM jobs, manually run the missed visible report, verify delivery, and still label research-only signals as `NO SETUP / WATCHLIST ONLY`. For objective/status/"are we tracking to the goal" audits, use `references/wolfy-objective-tracking-postgres-audit-2026-06-25.md`: restate the EOD/no-auto-execution constitution, query Postgres directly, use current `dt`-based schemas, summarize tracking vs the EOD constitution, and identify the next gate to reach paper-trade readiness. For "are we set up to loop / make progress" readiness audits, use `references/wolfy-loop-readiness-audit-2026-06-29.md`: separate active script-only loops from paused LLM loops, verify Postgres `prices`/`features`/`runs`, and diagnose Massive EOD ingest timeouts as shard/backfill engineering issues. For a compact “how are we progressing?” answer shape, use `references/wolfy-concise-progress-audit-2026-07-10.md`: anchor current time, cron health, usage-watchdog silence, visible ledger facts, strategy gates, and one next build target without over-explaining the architecture.

### Daily optimization planner / visible ledger pattern

For the daily Wolfy optimization planner, treat visibility itself as a safe high-value optimization when broader strategy/ledger migrations are too risky for the run. After the required cron/process/git conflict snapshot, maintain `/root/.hermes/wolfy/optimization_todo.md` with candidate impact plans, then prefer bounded read-only helpers such as a `visible_progress_ledger.py` that reports Postgres/cron facts: price/feature freshness, historical OHLCV depth, scanner freshness, signals/setups, strategy gate status, open positions, blockers, and one next action. Keep it deterministic, Markdown-table friendly, and explicit that `candidate` is not `approved`; it must not write DB rows, approve strategies, create setups, or imply live trading.

Daily optimization runs should send a short completion report when done, using the cron final response/delivery if available. Keep the report to the shortest useful form: `CHANGED` (1-3 bullets), `VERIFIED` (commands/status and commit hash if any), `KPI/STATE` (only notable deltas), `BLOCKED/HUMAN ASK` (Tier B only), and `NEXT ACTION`. If a 429/usage-limit event occurred, report only the event and timestamp; do not include raw matching log lines, stack traces, or dashboards unless explicitly requested. See `references/wolfy-daily-optimization-short-completion-reports-2026-07-01.md`.

If `budget_gate.py` reports `BUDGET=block` at the start of the optimizer run, switch to PLAN-ONLY instead of attempting implementation: complete deterministic orientation/review, run config guardian and `hermes cron list`, do not touch code/config/cron/LLM-job enablement, persist a small run/task state update, record `jobs_skipped_by_budget=1` plus relevant state metrics, update `optimization_todo.md` only if doing so is allowed under the current budget/probation constraints, and send the concise final report. Persist the next concrete task with a machine-checkable DoD (for example the next OWS item) rather than only describing a roadmap; if that task/state/metrics write succeeds, it is acceptable to finish the optimizer `agent_runs` row as `completed` with an explicit `Plan-only due to budget gate block` summary, while using `blocked` when no durable progress was made. If the only repository change is a verified ledger/doc update, a narrow local commit of that ledger is also acceptable after checking staged paths; if the ledger already contains earlier uncommitted daily entries, verify and intentionally include them or stage only the current hunk instead of blindly `git add`-ing the whole file. `wolfy_agent_cli.py task-ensure` currently prints `AGENT_TASK_ID=<id>` (not `TASK_ID=<id>`), so parse both names or copy the printed ID before updating DoD/claiming/starting the run. If `agent_tasks` has no explicit `commit_hash`/`verification_result`/`verified_at` columns, store that verification metadata in an existing JSONB field (`metadata` in the current schema; `payload` in older schema variants). If optimizer/ops probes repeatedly expect those verification fields as top-level columns, let Mike add nullable compatibility aliases mirrored from `metadata`/`payload`/`definition_of_done` and preserve them through `postgres_init.sql` plus canonical/profile `mike_safe_autorepair.py` rather than changing canonical task semantics; see `hermes-runtime-operations` reference `wolfy-agent-tasks-verification-aliases-2026-07-19.md`. Still verify whether the prior OWS item is truly complete: for OWS-1, the gate script existing is not enough — LLM cron jobs such as Jonah must themselves consult it and no-op with `skipped: budget`/`wakeAgent:false` before LLM spend. If wiring is incomplete, create a concrete next-action `agent_task` with DoD rather than claiming OWS-1 is done. If a prior config/orchestration change is still on probation, do not make another config/schedule/orchestration change until that probation is promoted or rolled back. Current CLI/schema nuance: `budget_gate.py` has no `--json` or `--status`; use plain output and `--no-record` for a no-extra-write check. `config_guardian.py` has no `--check`/`--health-json`/`--health --json`/`--status`; use bare `python wolfy/guardian/config_guardian.py`, `--skip-cli` for a cheaper check, or import `config_guardian.health(Path('/root/.hermes'))` for structured checks. `cron/jobs.json` may be a top-level object (`{"jobs": [...], "updated_at": ...}`) rather than a bare list, so parse with `jobs = obj.get('jobs', []) if isinstance(obj, dict) else obj` before iterating. The visible ledger lives at `wolfy/visible_progress_ledger.py`, `loop_metrics` uses `metric_key` (not `metric_name`) for canonical inserts, `agent_runs` uses `error_message` (not `error`), and data-health KPI queries should count active/enabled symbols from `universe` rather than a nonexistent `tickers` table. Current `universe` is a view whose ticker column is `symbol`; join with `prices.ticker` using `symbol AS ticker` instead of querying `universe.ticker`. Do not assume helper views such as `wolfy_ticker_data_load_status` exist in every environment; if absent, compute freshness/depth directly from `prices` grouped by ticker (`max(dt)` plus bar counts). `strategies.latest_oos_verdict` is currently boolean, so do not `coalesce(latest_oos_verdict, '')`; use `latest_oos_verdict is not null` or boolean predicates. `backtests` stores OOS state in top-level columns such as `survives_oos`, `is_sharpe`, `oos_sharpe`, `oos_cagr`, `max_dd`, and `turnover`, not a generic `metrics` JSONB column. In psycopg SQL, pass patterns such as `%optimization%` as parameters rather than embedding them in a query string where `%o` is parsed as a placeholder. Do not assume `agent_tasks.source_fingerprint` has a unique constraint: an `INSERT ... ON CONFLICT (source_fingerprint)` can fail with `InvalidColumnReference`; for plan-only dedupe, first `SELECT id,status FROM agent_tasks WHERE source_fingerprint=%s`, then `UPDATE` that row or `INSERT` a new one. If one psycopg statement fails during orientation/metrics, remember the transaction may have rolled back; verify task/run/metric rows before retrying. Commit safety nuance: this repo is often dirty from curator/profile/autorepair work, so always inspect `git diff --cached --name-status | cat` before committing; if unrelated paths are staged, `git restore --staged .`, add only the intended verified files, re-check the staged diff, and then commit. If a bad commit already included unrelated staged files, recover with `git reset --soft HEAD~1 && git restore --staged . && git add <intended files> && git commit ...`. If the same ledger file already has unrelated unstaged edits, stage only the intended hunk by creating a minimal patch for the new daily entry, applying it with `git apply --cached`, and inspecting `git diff --cached` before committing. For multi-statement metrics/task updates, prefer writing and running a small temporary Python script over fragile inline shell heredocs; remove the temp script after verifying output. See `references/wolfy-budget-gated-plan-only-optimizer-run-2026-07-01.md`, `references/wolfy-budget-gated-plan-only-optimizer-run-2026-07-02.md`, `references/wolfy-budget-gated-plan-only-optimizer-run-2026-07-03.md`, `references/wolfy-budget-gate-plan-only-run-ledger-2026-07-10.md`, `references/wolfy-budget-blocked-plan-only-and-staged-diff-safety-2026-07-11.md`, `references/wolfy-plan-only-budget-ledger-commit-2026-07-12.md`, `references/wolfy-plan-only-budget-task-persistence-2026-07-13.md`, `references/wolfy-plan-only-budget-gate-low-headroom-2026-07-14.md`, `references/wolfy-plan-only-budget-gate-low-headroom-2026-07-16.md`, `references/wolfy-plan-only-budget-gate-low-headroom-2026-07-17.md`, `references/wolfy-plan-only-budget-gate-low-headroom-2026-07-19.md`, `references/wolfy-plan-only-budget-gate-low-headroom-2026-07-20.md`, `references/wolfy-plan-only-budget-gate-token-cap-2026-07-23.md`, `references/wolfy-plan-only-budget-gate-token-cap-2026-07-24.md`, `references/wolfy-plan-only-budget-gate-token-cap-2026-07-25.md`, `references/wolfy-plan-only-budget-gate-token-cap-2026-07-26.md`, `references/wolfy-plan-only-budget-gate-low-headroom-2026-07-27.md`, `references/wolfy-plan-only-budget-gate-token-cap-2026-07-28.md`, `references/wolfy-plan-only-budget-gate-token-cap-2026-07-29.md`, `references/wolfy-plan-only-budget-gate-low-headroom-2026-07-30.md`, `references/wolfy-plan-only-budget-gate-token-cap-2026-07-31.md`, `references/wolfy-plan-only-budget-gate-token-cap-2026-08-01.md`, `references/wolfy-plan-only-budget-gate-token-cap-2026-08-02.md`, `references/wolfy-plan-only-budget-gate-token-cap-2026-08-03.md`, `references/wolfy-plan-only-budget-gate-token-cap-2026-08-04.md`, `references/wolfy-plan-only-budget-gate-token-cap-2026-08-05.md`, `references/wolfy-plan-only-budget-gate-token-cap-2026-08-06.md`, `references/wolfy-plan-only-budget-gate-low-headroom-2026-08-07.md`, `references/wolfy-plan-only-budget-gate-low-headroom-2026-08-08.md`, `references/wolfy-plan-only-budget-gate-low-headroom-2026-08-09.md`, `references/wolfy-plan-only-budget-gate-low-headroom-2026-08-10.md`, `references/wolfy-plan-only-budget-gate-token-cap-2026-08-11.md`, and `references/wolfy-plan-only-budget-gate-low-headroom-2026-08-12.md` (bind the plan-only task to the current cron `agent_runs` row via `HERMES_SESSION_ID` when possible, and isolate/rollback failed orientation queries so one psycopg schema miss does not abort the remaining probes). When `budget_gate.py` blocks for `low_headroom_pct`, its output may not include `tokens_today`; query today's `agent_runs` token sum directly before recording the KPI. Use `wolfy_agent_cli.py task-ensure` rather than a nonexistent `task-create`, and do not query `agent_runs.verification_result` because verification currently belongs in task fields/metadata and run summaries. For multi-statement metric/task writes, prefer a short temporary Python script over fragile inline shell/SQL, and remove the temp script after verification. Run metric/DoD writes and `task-complete`/`run-finish` as separate verified steps or under `set -euo pipefail`; do not chain completion commands after a fragile inline Python/SQL update unless failure will stop the shell. If a write step fails after a task/run was already marked completed, immediately re-query the task, run, and metric rows, repair missing DoD/KPIs, and only then report success. If the plan-only run safely produced a narrow ledger/doc-only repository update, it is acceptable to local-commit that verified file and store/report the unpushed hash; still stage only the intended hunk/file in the dirty Hermes repo. For ad-hoc direct data-health SQL in Python, schema-qualify `public.prices` and verify columns/search path before grouping by ticker.

When the user provides a one-time backlog/standards/architecture installation prompt, keep the run bounded exactly as requested: install verbatim sections in the specified files, create planning-only `agent_tasks` rows with deterministic dedupe fingerprints, commit narrow verified file blocks, push only after verification, and do not implement future backlog items in the same run unless explicitly allowed. If the prompt includes a watchdog state repair, prove actual provider health with a minimal live probe before clearing stale `limited_active` state. See `references/wolfy-backlog-installation-and-watchdog-repair-2026-07-01.md`.

When strategy/backtest readiness is in scope, include a historical-depth gate in the visible ledger before running or trusting walk-forward OOS results: aggregate `prices` by ticker for first/last date and bar counts, report min/median bars and count above/below the practical threshold, and choose a business-day threshold that matches the actual data calendar (for example a two-calendar-year U.S. daily history may be ~500 bars, not 504+). This lets the optimizer safely surface whether the universe is ready for validation without launching long data jobs during cron windows.

When backlog hygiene is in scope but allocator/stale-cleanup jobs are active or due soon, do **not** mutate `agent_tasks`/Kanban state from the daily optimizer. Instead, add/maintain a read-only backlog-hygiene snapshot in the visible ledger: queued/ready, in-progress, blocked, stale in-progress over a conservative threshold, and duplicate active `source_fingerprint` counts. Use those facts to choose the next bounded hygiene pass after worker/cleanup jobs are idle. This preserves active claims and avoids creating task-state races while still giving the user visible progress.

When the user explicitly asks to clear/supersede blocked Wolfy tasks, distinguish active Postgres `agent_tasks.status='blocked'` rows from historical `agent_runs.status='blocked'` noise in the visible ledger. Audit the blocked task IDs, verify whether later artifacts/recommendation state supersede them, then complete only the intended stale tasks with a clear `summary`, cleared `error_message`/`blocker_reason`, and `payload.cleanup_*` metadata. Verify `agent_tasks` blocked count reaches zero; warn that old `agent_runs` blocker rows can still appear as historical noise. See `references/wolfy-blocked-task-supersede-cleanup-2026-07-16.md`.

When strategy/backtest readiness is in scope but strategy edits or OOS runs are too broad for the daily throttle, add/maintain a read-only deterministic strategy-readiness section in the visible ledger. Join `strategies`, `signals`, and `setups` to report each strategy's status, latest signal date/count, total signals, latest setup date, open/pending setup count, and a gate note. Explicitly label non-approved strategies as research/watch-only (`candidate is not approved`) even when deterministic signals exist. This is a safe precursor to strategy definition/OOS work and avoids implying actionable setups.

When the user explicitly asks to start getting recommendations, optimize the **recommendation pipeline gate**, not broad scanner/research volume. Build one narrow deterministic EOD strategy first, keep it `research_only` until validation, promote at most to `candidate` after evidence, and require explicit human approval before `approved` or any actionable/paper recommendation generation. For this user’s current options-focused path, implement `liquid_rs_breakout_continuation` first: 5-day high breakout, 20-day relative strength vs SPY, `vol_ratio >= 1.2`, within 5% of recent high, stop below prior 5-day low, max 10 trading days, partial at 1.5R then trail, 2–3 week slightly OTM call-spread expression. Save a durable plan, then create ordered Postgres `agent_tasks` with stable fingerprints and dependencies: seed strategy -> deterministic signals -> broad/current universe with tradability/manipulation/data-quality gates -> validation gates -> validation run -> approved-gated recommendation writer -> Sentinel/Yang review -> **Postgres paper-trade auto-logging gate** -> visible ledger section -> **underlying setup-success post-review gate**. Treat user language like "go for recommendations" as approval to build the engine, **not** approval to mark a strategy approved or execute trades. For this user, once a strategy is approved and both Sentinel and Yang approve a setup, paper trades may be auto-logged for learning/evaluation in Postgres `paper_trades` only; do not use SQLite or any broker/live-execution path. Options liquidity/OI/volume/spread are informational and user-evaluated, not hard gates. Evaluate recommendation success by whether the **underlying stock/ETF technical setup** continued higher and by how much, not by the user’s actual option fill/P&L. See `references/wolfy-recommendation-engine-agentic-plan-2026-07-19.md`, `references/wolfy-recommendation-engine-interview-decisions-2026-07-19.md`, and `references/wolfy-options-recommendation-engine-underlying-review-2026-07-30.md`.

When `paper-postgres` or accountability visibility is in scope but true paper-ledger migration is too broad for the daily throttle, add/maintain a read-only paper/accountability gate in the visible ledger. Query Postgres `paper_trades` and `recommendations` only; report total/open paper trades, open trades missing stops, closed PnL total, latest paper trade date, total/pending recommendations, and pending recommendations missing stops. Render an explicit gate note such as `paper/accountability only; no live trading or auto-execution`. This advances the paper-ledger migration trail by exposing facts without schema changes, consumer rewrites, setup creation, or any trading action.

When the visible ledger has multiple safety-critical sections and further functional additions would exceed the daily throttle, a valuable bounded optimization is to add render-level regression tests for `/root/.hermes/wolfy/visible_progress_ledger.py`. Use a synthetic `collect_progress()`-shaped dict so tests do not touch Postgres, and assert the output preserves EOD-only/no-auto-execution/human-approval language, `candidate is not approved`, paper/accountability-only wording, and the core Markdown sections. See `references/wolfy-visible-ledger-regression-tests-2026-06-26.md`.

When updating the Wolfy daily self-improvement / optimization cron prompt, treat the user's latest uploaded prompt as the source of truth and verify exact installation with distinctive prompt markers before claiming it was read. For the earlier conservative optimizer shape, keep the prompt compact but preserve the loop state machine: orient from deterministic state, review previous `in_progress` work, plan from real blockers/backlog, execute ≤1–2 Tier A slices, verify a machine-checkable DoD, commit only verified work, record `loop_metrics`, and leave one lesson/next action. Add the planning guard `If WS-1 is not complete, WS-1 is the default next task unless Priority 1 health is broken.` Treat schedule/config changes, installs, repo untracking/deletes, and strategy approvals as Tier B recommendations unless the user explicitly approves them. See `references/wolfy-daily-self-improvement-loop-prompt-2026-06-30.md`.

For the newer self-optimizing control-plane prompt, the autonomy model changes: cron schedules, `config.yaml`, orchestration parameters, structural refactors, and Postgres-only migrations become Tier S autonomous work only after OWS-1/OWS-2 guardians exist and under the Self-Modification Protocol; Tier B narrows to installs/upgrades, new credentials/API keys/secrets, and strategy approval. Verify markers such as `Tier S — SELF-OPTIMIZE AUTONOMOUSLY`, `SELF-MODIFICATION PROTOCOL`, `OWS-1 — Proactive budget gate`, and `OWS-2 — Config guardian` after installing. Commit only `cron/jobs.json` for prompt updates, leave unrelated dirty skill/curator/profile files untouched, and push only if the user explicitly asks. See `references/wolfy-self-optimizing-loop-control-plane-2026-06-30.md`.

When bootstrapping the self-modification safety layer after LLM quota/429 pressure, build deterministic guardians before re-enabling LLM jobs: a `budget_gate.py` that proves ok/block behavior with simulation and records `usage_headroom_pct`, then a `config_guardian.py` with known-good snapshots, expired-probation rollback, and a real restore proof. Schedule the guardian through a wrapper under `~/.hermes/scripts/`; only after OWS-1/OWS-2 pass should you apply one reversible config change on probation, such as `cron.max_parallel_jobs=1` and `kanban.max_in_progress_per_profile=1`. If the real gate says `BUDGET=block codex_usage_limited`, leave LLM jobs paused and report that re-enable is blocked. See `references/wolfy-orchestration-bootstrap-guardian-2026-06-30.md`.

Verification pitfall: avoid `python script.py | python3 -c ...` or similar output-truncation pipes into interpreters; Tirith may block them as pipe-to-interpreter. Prefer full output, temp files, or script-level compact flags.

Budget-gated LLM cron pitfall: for LLM cron jobs with pre-run context scripts, printing `skipped: budget` is not enough to prevent token spend. The script must make the cron scheduler skip the agent by emitting a final non-empty JSON line `{"wakeAgent": false, "reason": "skipped: budget"}` when `wolfy/guardian/budget_gate.py` blocks. Put the budget check in the cron-facing wrapper before any context generation that can claim tasks or open `agent_runs`; keep normal smoke mode (`WOLFY_CONTEXT_SMOKE=1`) working when the gate passes. `budget_gate.py` may return a nonzero exit status when it prints `BUDGET=block`; wrappers should parse the first non-empty stdout/stderr line and treat `BUDGET=block...` as the skip condition regardless of exit code, then emit the final wake-gate JSON. For self-modification probation markers consumed by Wolfy's config guardian, use keys `created_at` and `expires_at` (not `created_at_utc`/`expires_at_utc`) or the guardian may treat the marker as malformed and restore known-good. See `references/wolfy-jonah-budget-wake-gate-2026-07-07.md`.

Runtime pitfall: Wolfy cron/Hermes venv contexts may have `psycopg`/psycopg3 while system `python3` may only have `psycopg2`. Read-only/manual helpers that operators run directly from the shell should either use the Hermes/uv environment or include a psycopg3-to-psycopg2 fallback; otherwise visibility checks can falsely show Postgres unavailable even though cron jobs work.

Massive/Polygon + EODHS/EODHD data-source pattern: store credentials only in Hermes `.env` as `MASSIVE_API_KEY` and `EODHS_API_KEY`/`EODHD_API_KEY` (never in code/logs). Wolfy's EOD price path prefers `/root/.hermes/wolfy/eod_price_features.py --source massive`; the cron wrapper `/root/.hermes/scripts/wolfy_eod_after_close_ingest.py` defaults to Massive adjusted EOD bars, with Yahoo and EODHS as explicit fallback/smoke sources only.

When the user asks what technical-only signals or data sources to add, separate **derived indicators** from **new information**. Compute RSI/MACD/ADX/Bollinger/ATR/MA slopes, breadth, relative strength, volatility contraction, price-structure, and richer volume features locally from canonical OHLCV; do not pay another API for vendor-computed transforms of the same bars. Spend only for orthogonal datasets or materially deeper adjusted history. Prefer free official Cboe volatility/put-call regime data first; treat FINRA short-sale volume and Nasdaq short interest as research features until validated. For roughly $30/month, compare Tiingo Power (deep adjusted EOD history) against Massive Starter (minimal integration friction, five-year history). Before mixing bar vendors, add row-level source/adjustment provenance and prevent cross-check data from silently overwriting canonical bars. Never substitute an IEX-only volume feed for consolidated U.S. volume. Add feature families one at a time and require chronological setup-outcome improvement before promotion. See `references/wolfy-technical-data-source-selection-and-signal-expansion-2026-08-12.md` for the source review, provider limits, recommended signal families, and official links.

Robinhood/MCP is useful as read-only broker/tradability/options enrichment rather than the canonical backtest source: it can provide up to about 5 years of stock/ETF OHLCV (`open_price`, `close_price`, `high_price`, `low_price`, `volume`) plus quotes, fundamentals, options chains/Greeks/IV/open interest where exposed, and account/position context; use it after deterministic Wolfy recommendation rows exist, not as the source of trading decisions. See `references/robinhood-mcp-data-capabilities-2026-08-08.md`. Massive reference pagination can hit 429 per-minute limits; use retry/backoff and avoid fetching all reference pages more often than needed. For free-tier protection, EOD ingest should fetch incrementally from the latest stored date once each ticker has adequate history; EODHS fallback is capped (`--eodhs-fallback-max-tickers`, default 0) and should be used only for small missing-ticker/cross-check pulls. For one-time Massive backfills, verify actual returned/stored depth rather than requested lookback; free-tier aggregates may return only about two years/~501 bars even when five years are requested. Treat the two-year history load as **bootstrap-only**: daily EOD jobs must not repeatedly reload two years after readiness; they may pass `--days 730` only as a bootstrap floor if the fetch plan proves loaded tickers use `latest_dt + 1` / `already_current`. Full-history refetch is reserved for deliberate repair cases such as corporate-action/split adjustment-basis repair. Make bounded backfill jobs visibly run-until-complete, auto-disable, or no-op after active targets meet `DEPTH_READY_BARS`/`min_history_bars=495`, and report bootstrap remaining separately from daily freshness. Use bounded universes, a per-ticker pause, and `uvx --with 'psycopg[binary]' python ...` when manual Postgres scripts need psycopg. Verify integration with adjusted bar ingest, feature recompute, data-quality validation, and then rerun deterministic signal generation so `prices`, `features`, and `signals` share the latest date. For the concrete backfill command, verification queries, and docs scope (stocks/options/indices only), see `references/wolfy-massive-free-tier-backfill-and-docs-2026-06-26.md`; for the bootstrap-vs-daily-incremental TODO/audit pattern, see `references/wolfy-one-time-massive-bootstrap-vs-daily-incremental-2026-07-02.md`. Massive docs scope for Wolfy should exclude crypto/forex/futures/alternative-data unless the user explicitly changes scope.

Python/Postgres driver pitfall for read-only status helpers: if a Wolfy ledger/context helper must run from both manual `python3` shell checks and Hermes/cron environments, make its Postgres connection tolerant of psycopg3 and psycopg2 rather than treating `ModuleNotFoundError: psycopg` as a hard ledger failure. Prefer psycopg3 with `dict_row`, fall back to `psycopg2.extras.RealDictCursor`, then verify with `python3 -m py_compile`, Markdown output, and JSON output. This is especially useful for `/root/.hermes/wolfy/visible_progress_ledger.py`. See `references/wolfy-visible-ledger-python-driver-fallback-2026-06-25.md`.

When tiered universe/backfill readiness is in scope, add/maintain a read-only data-load status section in `/root/.hermes/wolfy/visible_progress_ledger.py`: join Postgres `universe` to per-ticker `prices` coverage and render tier, universe count, active/enabled count, tickers with prices, tickers with readiness-threshold bars, missing-price count, backfill-attention count, median/min bars, and latest price date. Use this to defer broad OOS validation until active enabled tier coverage is adequate, without launching broad unbounded backfills during the daily optimizer. Current Massive free-tier practical readiness is `DEPTH_READY_BARS=495`, because two-calendar-year pulls can return 499 bars; using a hard 500-bar threshold caused repeated re-fetching of the same tickers. For autonomous backfill, use `/root/.hermes/scripts/wolfy_tiered_backfill_bounded.py` (`backfill_tiered_remaining.py --min-history-bars 495 --max-batches 4`) scheduled as no-agent/local so it advances a few tickers per run under the cron timeout.

Orchestration refactor pattern: keep Hermes cron-facing script filenames stable under `/root/.hermes/scripts/`, but move duplicated constants/command construction behind shared Wolfy modules. Current shared modules are `/root/.hermes/wolfy/orchestration_config.py` for `CORE_EOD_UNIVERSE`, `EOD_INGEST_SHARDS`, default source/lookback, and readiness bars, plus `/root/.hermes/wolfy/orchestration_runner.py` for EOD ingest/signals subprocess construction and dry-run handling. Verify such changes with py_compile, wrapper unit tests (`test_eod_after_close_ingest_wrapper.py`), no-write dry-run ingest/signals smoke, and shard import/monkeypatch command smoke rather than executing live shard market-data pulls. See `references/wolfy-orchestration-refactor-and-scratch-cleanup-2026-06-29.md` for the concrete implemented module/wrapper shape and cleanup verification pattern.

When the user asks about orchestration-layer refactors, prefer a bounded wrapper/config consolidation before strategy-engine or autorepair rewrites. Audit cron-facing script names and duplicated constants first; then centralize stable values such as `CORE_EOD_UNIVERSE`, shard groups, default lookback/source, and `DEPTH_READY_BARS` in a small Wolfy orchestration config module while preserving existing `/root/.hermes/scripts/` filenames as thin cron shims. Add a shared runner only for consistent subprocess invocation, JSON logging, dry-run behavior, exit codes, and path setup. Defer `mike_safe_autorepair.py` decomposition until focused tests exist because it is a live guardrail with a higher blast radius. See `references/wolfy-orchestration-refactor-audit-2026-06-29.md`.

See `references/wolfy-daily-optimization-ledger-2026-06-19.md` for the concrete initial sequence, `references/wolfy-visible-progress-historical-depth-gate-2026-06-20.md` for the historical-depth gate pattern, `references/wolfy-visible-progress-backlog-hygiene-snapshot-2026-06-21.md` for the read-only backlog-hygiene snapshot pattern, `references/wolfy-visible-progress-strategy-readiness-2026-06-22.md` for the deterministic strategy-readiness ledger pattern, `references/wolfy-visible-progress-paper-accountability-gate-2026-06-25.md` for the read-only paper/accountability gate pattern, `references/wolfy-visible-ledger-python-driver-fallback-2026-06-25.md` for dual psycopg/psycopg2 ledger verification, `references/wolfy-data-load-status-audit-2026-06-27.md` for the compact “did we load the data?” audit pattern using visible ledger plus tiered Postgres coverage queries, `references/wolfy-massive-postgres-history-status-audit-2026-07-02.md` for the direct Massive two-year-history-in-Postgres audit using `prices`/`features` plus `universe_backfill_targets` and the practical ≥495-bar threshold, and `references/wolfy-visible-ledger-tiered-data-load-status-2026-06-27.md` for the exact read-only tiered data-load ledger implementation/verification pattern.

## Wolfy durable DB workflow

For this user's Wolfy setup, the active direction is **Postgres-only for all Wolfy live operations**: PostgreSQL database `wolfy` is the operational source of truth. Do not route live cron/report/scanner/recommendation paths through `/root/.hermes/wolfy/wolfy.db`; that live SQLite database has been retired and deleted after parity verification. If a Wolfy live component still needs SQLite, treat it as a migration bug, not an acceptable fallback. Python's/OS SQLite may still appear in Hermes internals such as `state.db` or Kanban; that is not Wolfy's market database.

### SQLite retirement / Postgres-only migration protocol

When the user asks to retire SQLite or finish migrating Wolfy to Postgres:

1. Inventory all live consumers before editing: global/profile cron job prompts, wrapper scripts under `/root/.hermes/scripts/`, Wolfy scripts under `/root/.hermes/wolfy/`, and context generators for Wolfy/Jonah/Sentinel/Yang/Clerky/Mike.
2. Treat SQLite use in live scanner/report/recommendation/alpha/context paths as a migration bug. Patch those paths to use Postgres, fail clearly when Postgres is unavailable, or mark the component as legacy-only.
3. Keep token costs low during rate-limit periods: script-only checks first, concise status tables/bullets only, no large narrative reports unless a real anomaly or user decision requires it.
4. Verify with real smoke outputs before claiming completion: Python compile checks, Postgres row counts for migrated tables, representative context-script execution, and cron prompt validation.
5. If the user explicitly approves deletion, first prove row coverage in Postgres (`wolfy_retired_legacy_rows` plus native Postgres tables), then remove live DB artifacts and obsolete SQLite sync/init/queue helpers. Do not reintroduce SQLite fallback paths afterward.

See `references/wolfy-sqlite-retirement-postgres-only-2026-06-07.md` for the concrete migration/verification pattern from the Postgres-only cutover session.

Core files:

- `/root/.hermes/wolfy/wolfy_postgres_pipeline.py` — Postgres scanner/universe/recommendation persistence.
- `/root/.hermes/wolfy/postgres_init.sql` — Postgres schema and scale-up foundation.
- `/root/.hermes/wolfy/sources/inbox/` — user-provided source-file drop zone; ingest must write Postgres, not retired SQLite.
- `/root/.hermes/wolfy/wolfy_scanner.py` — scanner; live paths persist to Postgres `scanner_runs` and `scanner_results`.
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

Honesty rule: Wolfy may only claim durable learning if it inserted records into Postgres-backed knowledge/artifact tables (`knowledge_chunks`, `agent_artifacts`, `strategy_rules` view/source, or successor Postgres tables), and it must distinguish public/framework-level learning from user-provided book/material ingestion.

Scale-up thresholds and current scale-up foundation:

- Postgres is now the intended primary operational source of truth; SQLite remains a legacy compatibility/fallback store until each live consumer is migrated and verified.
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

Postgres knowledge chunk verification pitfall:

- `knowledge_chunks` does **not** have top-level columns named `embedding_provider`, `embedding_model`, or `embedding_method`; provider/model/method metadata is stored in the `metadata` JSONB field. Verify embedding coverage with `count(embedding)`, and query metadata as `metadata->>'embedding_provider'`, `metadata->>'embedding_model'`, etc. Do not add compatibility alias columns for these unless a real consumer requires them; the safe ops check is:
  ```sql
  select count(*) total, count(embedding) embedded, count(*)-count(embedding) missing from knowledge_chunks;
  select coalesce(metadata->>'embedding_provider','NULL') provider,
         coalesce(metadata->>'embedding_model','NULL') model,
         count(*)
  from knowledge_chunks
  group by 1,2
  order by 3 desc;
  ```

Knowledge/objective conflict-audit and retrieval-prune pattern:

- When the user asks whether Wolfy's learning conflicts with the technical swing-trading objective, answer from database evidence, not vibes. Count technical setup chunks, EOD/research-only gate language, broader catalyst/fundamental/risk-context chunks, and potential conflict terms such as live/auto execution, intraday/day-trading instructions, crypto/forex/futures, shorts, and unapproved strategy recommendations.
- Distinguish **direct conflict** from **retrieval dilution**. If conflict-looking terms appear as risk gates, provenance, SEC fields, or explicit no-action language, say they are context/gates rather than contrary instructions. If they appear as instructions to trade outside the constitution, recommend quarantine/relabeling.
- If the user asks to focus all token consumption on technical trading, narrow the **retrieval/search surface** rather than deleting safety source-of-truth. Archive deleted chunks, keep technical setup/Yang/EOD/risk/account/approval guardrails, remove fundamental/catalyst/company-story/filing/valuation/alpha-lead narrative chunks, trim source rows that would re-sync removed notes, re-embed, and verify `count(*) == count(embedding)` plus technical smoke-query hits.
- Always report `strategies.status` and whether any strategy is `approved`; if none are approved, the correct conclusion is research/watch-only even if the knowledge base is useful.
- See `references/wolfy-knowledge-chunk-objective-audit-and-log-hygiene-2026-07-09.md` for the compact audit table shape and wording. See `references/wolfy-technical-retrieval-prune-2026-07-10.md` for the concrete technical-only retrieval pruning workflow and report shape.

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

Coordination pitfall: context generators should claim only fresh queued work, not stale local `in_progress` rows. Re-selecting stale SQLite `in_progress` work can create repeated Postgres `agent_runs.status='blocked'` rows with `duplicate-or-already-claimed` every cron tick. Leave stale `in_progress` cleanup to `wolfy_cleanup_stale_agent_coordination.py` and verify post-fix with a duplicate-count query. See `references/wolfy-jonah-coordination-noise-2026-06-02.md`.

Autorepair pitfall: recurring Mike/safe-autorepair jobs must not run DB-mutating smoke tests such as `test_agent_coordination_smoke.py`; repeated production cron runs can create synthetic blocked tasks (for example `Sentinel / Smoke blocked task`) that pollute the queue. Keep frequent autorepair checks idempotent/read-only or explicitly productive, run DB-mutating smoke tests manually/CI only, sync patched wrappers across global/Wolfy/profile script copies, and clear proven synthetic blockers by marking them completed with an explanatory note rather than deleting rows. See `references/wolfy-autorepair-nonmutating-health-checks-2026-06-11.md`.

Use this chain for auditable trade ideas: Jonah research note -> strategy rule -> scanner result -> Wolfy recommendation -> Sentinel review -> paper trade/watchlist status -> outcome grading.

Signal/provenance explanation pattern: when the user asks what Wolfy's signals are, whether volume is used, or where market data comes from, inspect current code and Postgres rather than inferring from names. Separate hard gates, advisory fields, liquidity/risk filters, governance status, and recommendation eligibility; trace vendor field -> `prices` -> derived `features` -> strategy threshold; exclude synthetic fixtures from current-state claims. See `references/wolfy-signal-and-market-data-provenance-audit.md`.

Scanner acceleration pattern for this user: when asked to "get more in there sooner," improve deterministic coverage before increasing LLM work. Add/refresh a liquid U.S. universe cache, compute volume/breakout/squeeze/relative-strength/liquidity factors, run script-only intraday scanner snapshots, and auto-create structured alpha-lead handoffs from top anomalies. Treat scanner outputs as leads, not recommendations, until they pass promotion, Sentinel, Yang/technical review, and paper-ledger gates. A scanner freshness gate should run before decision reports; stale data means no actionable recommendation. For cron-bounded intraday snapshots, prefer rotating bounded batches (for example `--max-symbols 32`) persisted to Postgres over full-universe scans that exceed the no-agent timeout; keep successful runs silent and verify fresh `scanner_runs`/`scanner_results` rows before calling scanner freshness healthy.

Options-focused recommendation-engine planning and implementation pattern: when the user wants 1–2 week options recommendations, do not default to a slow pullback-to-20MA equity swing. Prefer interviewing toward a tightly specified relative-strength breakout/short-consolidation strategy because options need cleaner timing and less premium bleed. The current user-approved first implementation target is `liquid_rs_breakout_continuation`: prior 5-day high breakout, 20-day relative strength vs SPY, `vol_ratio >= 1.2`, close within 5% of recent high before breakout, stop below prior 5-day low, 10 trading-day max hold, partial at 1.5R and trail remainder, 2–3 week slightly OTM call spreads preferred, Sentinel+Yang approval required before Postgres-only `paper_trades` auto-log. By user correction, options liquidity/OI/volume/spread should be surfaced as information/warnings when available, but **not** used as a hard paper-recommendation or paper-logging gate; the user evaluates liquidity manually when placing any real trade. Post-review should grade the underlying setup accuracy and continuation magnitude, not user option fill/P&L. Implement the first slice with TDD: write failing strategy-seed and deterministic-signal tests, add the `DEFAULT_STRATEGIES` row, add `_generate_liquid_rs_breakout`, verify no setup rows are created while `research_only`, then run `test_eod_signals.py -q` and the full Wolfy pytest suite before committing narrow intended files only. For Wolfy tests that touch shared Postgres, isolate fixtures with synthetic `ZZ...` tickers plus far-future dates such as `2099-*`, and cleanup every table the flow writes before using the same database for historical validation. If test fixtures must use live benchmark tickers such as `SPY`, cleanup only far-future fixture rows and never delete real benchmark history. Before validating RS strategies, verify SPY benchmark history exists and ingest it via the normal EOD wrapper if missing. If validation fails the user's gates, stop the recommendation-writer path, keep the strategy `research_only`, record auditable failure reasons, and queue deterministic rule revision before any recommendation or paper-trade work. When exhausting a failed setup, add a deterministic underlying setup-outcome evaluator and mine historical success cohorts before abandoning it. For options-timed Wolfy strategies, validate the actual underlying thesis with a setup-outcome-native gate rather than relying only on next-close return backtests: target hit before invalidation, stop/invalidation rate, median MFE/MAE in R, and a frequency-aware chronological OOS tail. In this implementation sequence, broad RS breakout failed, the small-sample `liquid_rs_breakout_tight_risk_volume` revision remained unpromoted, and the more robust `liquid_rs_breakout_close_confirm_1r` variant passed setup-outcome validation: SPY > 50SMA, RS excess >=2%, `vol_ratio >=1.2`, prior-low risk <=5%, invalidation on close back below breakout level, 1R target, max 10 trading days. The user subsequently approved `liquid_rs_breakout_close_confirm_1r` for **paper recommendations/logging only** and allowed future same-gate-passing strategies to auto-activate for paper-only recommendations. This paper-testing approval does not grant live execution or money movement. For this paper-only mode: bypass Sentinel/Yang review gates, immediately log deterministic approved-strategy signals to Postgres `paper_trades`, risk 5% per paper trade, no max-open cap, max 3 paper-eligible recommendations per day, use EOD close as paper-entry baseline, daily summary only, and log equity fallback plus option-spread structure when data exists. Do not let live-DB tests reset real strategy governance fields; isolate fixtures with synthetic tickers/future dates and preserve benchmark history such as SPY. See `references/wolfy-options-recommendation-engine-interview-2026-07-29.md`, `references/wolfy-recommendation-engine-interview-and-options-strategy-2026-07-29.md`, `references/wolfy-options-recommendation-engine-underlying-review-2026-07-30.md`, `references/wolfy-rs-breakout-strategy-tdd-implementation-2026-07-30.md`, `references/wolfy-rs-breakout-validation-and-live-db-fixtures-2026-07-30.md`, `references/wolfy-rs-breakout-tight-risk-revision-2026-07-30.md`, `references/wolfy-rs-breakout-setup-outcome-exhaustion-2026-08-03.md`, `references/wolfy-rs-breakout-setup-outcome-validation-gate-2026-08-03.md`, `references/wolfy-paper-recommendation-activation-decisions-2026-08-03.md`, and `references/wolfy-approved-paper-recommendation-writer-2026-08-06.md` for the full decision set, implementation slice, validation result, fixture-isolation pitfall, row-flow, tight-risk revision findings, exhaustive grid, setup-outcome validation gate, final paper-activation decisions, and approved-gated paper recommendation writer implementation/verification pattern.

## Implementation Kanban acceleration

When this user asks to "Kanban" Wolfy build priorities and complete them without prompting, act as an implementation orchestrator, not just an analyst:

1. Inspect the current Wolfy board and cron state before creating cards, so existing blocked/todo cards are reused instead of duplicated.
2. If a card is blocked only for review and has a worker handoff, rerun the cited verification commands. If they pass, comment with the real output and complete/unblock it so downstream dependencies can move.
3. Create dependency-linked cards for the accountability loop rather than flat independent tasks: scanner freshness -> lead promotion -> report integration; recommendation logger -> Sentinel persistence -> paper portfolio/outcomes; then an end-to-end smoke/cron handoff card depending on both lanes.
4. Save a durable project plan in `/root/.hermes/wolfy/` and reference it from the cards.
5. Comment on active cards that routine code/test/schema-compatible implementation should proceed autonomously; workers should block only for destructive DB/package changes, paid credentials/APIs, broker/live-trading authority, legal/data-access blockers, or human strategy approval.
6. Use idempotency keys when creating durable cards, especially after an interrupted session, so retrying the continuation does not duplicate the graph.
7. Run `hermes kanban dispatch --dry-run --max N --json` before the real dispatch when creating dependency graphs; confirm only independent parent cards would spawn, then run `hermes kanban dispatch --max N --json` and verify with `hermes kanban list`, `hermes kanban stats`, and `hermes kanban runs <task_id>`.
8. When continuing an interrupted Wolfy build prompt, first reconstruct the prior intent from session history, re-ground with profile discovery + current board/ledger facts, then create the next dependency-linked graph. Do not rely on memory alone. See `references/wolfy-interrupted-build-kanban-continuation-2026-07-10.md`.

- `references/wolfy-accountability-loop-kanban-plan-2026-06-01.md` — concrete dependency graph and verification pattern for Wolfy's accountability-loop implementation push.
- `references/wolfy-daily-self-improvement-loop-prompt-2026-06-30.md` — conservative optimizer prompt pattern: deterministic orient/review/plan/execute/verify/commit loop, Tier B recommendations for config/schedule/installs/strategy approvals, and source-of-truth prompt installation verification.
- `references/wolfy-daily-optimization-short-completion-reports-2026-07-01.md` — user preference and prompt pattern for short daily optimization completion reports, including concise 429/usage-limit event reporting.
- `references/wolfy-clerky-deterministic-ledger-context-2026-06-01.md` — deterministic pre-run context for Clerky's four-hour administrative ledger so schema-sensitive facts are gathered by script instead of guessed by the LLM.

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
- `references/wolfy-postgres-primary-optimization-2026-06-02.md` — Postgres-primary migration direction, Kanban card graph, verification commands, and wording correction: optimize role alignment/distribution, do not say “metabolize.”
- `references/wolfy-visible-progress-audit-2026-06-18.md` — user-visible progress audit pattern: distinguish paused LLM/report jobs from still-running script-only backend jobs, inspect usage-limit watchdog state, resume if limits cleared, and report EOD gates/DB counts plainly.
- `references/wolfy-eod-historical-depth-and-strategy-gates-2026-06-18.md` — EOD historical depth and validation-gate pattern: verify/extend OHLCV depth, regression-test ingest defaults, backfill features/signals, keep candidate strategies non-actionable until human approval, and report concrete progress when the user cannot see activity.
- `references/wolfy-objective-tracking-postgres-audit-2026-06-25.md` — objective/status audit pattern: inspect the `wolfy` Postgres DB directly, use current `dt`-based schemas, summarize tracking vs the EOD constitution, and identify the next gate to reach paper-trade readiness.
- `references/wolfy-candidate-validation-gate.md` — candidate-validation pattern: deterministic OOS success can promote `research_only -> candidate`, but never implies approval; report adverse IS/drawdown/turnover/setup caveats and keep recommendations watch-only without an approved strategy gate.
