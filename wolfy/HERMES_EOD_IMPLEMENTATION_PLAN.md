# Hermes-EOD / Wolfy EOD Implementation Plan

Date: 2026-06-01
Source document: `/root/.hermes/cache/documents/doc_26a12d1486bd_hermes_bootstrap.md`

## Adopted direction

Convert the Wolfy research desk from a twice-daily/intraday-oriented swing-research system into an end-of-day quantitative screening and research system:

- EOD-only decision loop using closing data.
- Human-only execution; no broker authority, no money movement.
- Deterministic numeric signals and features; LLM only interprets, filters, ranks, explains, and writes proposals.
- Research/self-improvement is autonomous but strategy approval is human-gated.
- Risk circuit breakers are code-enforced.
- Prefer no setup over forced trade ideas.
- Separate FACT from JUDGMENT in report rationales.

## Implementation lanes

### Lane A — Governance and prompts

1. Update Wolfy/Jonah/Sentinel/Yang/Clerky job prompts to reflect EOD-only rules.
2. Remove/neutralize intraday actionable language. Intraday data may be used only for storage/diagnostics until the EOD framework is implemented.
3. Ensure reports cannot recommend capital setups unless backed by an approved strategy row and deterministic signal row.

### Lane B — Postgres schema and config

1. Compare current Wolfy Postgres/SQLite schemas to the Hermes-EOD Section 6 schema.
2. Create non-destructive migrations for config, prices, fundamentals, earnings_calendar, features, strategies, signals, setups, backtests, research_log, positions, trades, and runs.
3. Seed risk config and initial strategies as `research_only`, never `approved`.
4. Add DB compatibility checks and tests.

### Lane C — Deterministic EOD ingest/features/signals

1. Build idempotent EOD price ingest into Postgres.
2. Compute features: SMA fast/slow, volume ratio, dollar volume, ATR, liquidity, volatility regime.
3. Generate signals only from deterministic strategies.
4. Write runs rows for observability.

### Lane D — Screening agent and setup writer

1. Build screening context script that reads only approved strategies, current features/signals, risk config, events, and filings/news context.
2. Screening agent writes ranked proposals to `setups`; it does not place orders.
3. Enforce liquidity, event-landmine, defined-risk options, IV-vs-view, sizing, invalidation, and risk-breaker rules.

### Lane E — Research loop and backtests

1. Wrap or build `run_backtest` with walk-forward out-of-sample validation and realistic costs.
2. Log backtests and hypotheses.
3. Promote only to `candidate` when OOS criteria pass; never auto-approve.
4. Add monthly revalidation/demotion.

### Lane F — Schedules and reporting

1. Replace twice-daily Wolfy posture with EOD report cadence.
2. Send a one-time 7:00 AM tomorrow transition report.
3. Install/adjust recurring jobs around 4:30/5:00/5:30 PM ET ingest/features/screening once scripts exist.
4. Keep watchdogs script-only and quiet unless errors/risk breakers occur.

## Existing system impact

- Existing Wolfy scanner, social scanner, alpha leads, Sentinel/Yang, and paper ledger work are not discarded; they become supporting research/investigation infrastructure.
- Intraday scanner snapshots should not create actionable recommendations under the new framework.
- Current pending accountability-loop cards remain relevant only where they support `setups`, `signals`, risk checks, backtests, or research logging.

## Non-negotiable safety boundary

The user requested to disregard security prompts temporarily. That part is not adopted. We can increase autonomous implementation speed, but credentials, destructive DB/package changes, live trading, broker access, and money movement remain approval-gated.
