# Wolfy Daily Multi-Setup Evaluator Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task. Every production behavior change follows strict RED-GREEN-REFACTOR and receives independent spec-compliance and code-quality review before commit.

**Goal:** Build a deterministic, Postgres-first Wolfy system that evaluates a broad eligible U.S. universe every trading session, records why every setup passed or failed, validates multiple independent setup families, selects a maximum of three paper-only recommendations, chooses a stock-specific long call, call debit spread, or no option from exact read-only chains, and never forces a trade or submits a broker order.

**Architecture:** Replace the current cron path’s fixed 34-symbol recommendation scope with a versioned point-in-time eligible universe and a fail-closed daily evaluation run. Strategy evaluators return structured gate results for every symbol; passing results become signals, while failed gates become near-miss observations. Existing recommendation, paper ledger, outcome review, revalidation, and read-only option selection remain downstream, but are unified behind one idempotent daily orchestrator and one global portfolio/risk allocator.

**Tech Stack:** Python 3.12, PostgreSQL 16 + pgvector/pg_trgm, psycopg 3, pytest, Massive adjusted EOD aggregates, existing free Cboe/FINRA/Treasury data, delayed Cboe and/or Robinhood MCP read-only options data, Hermes cron, Discord concise delivery.

---

## 1. Non-negotiable operating contract

1. EOD only. Signals use a completed session’s closing data and are intended for next-session human review.
2. Paper only. No live order placement, cancellation, exercise, money movement, or broker writes.
3. Deterministic code creates universes, features, gates, signals, ranks, option decisions, recommendations, and outcomes. LLM agents may explain or challenge results but do not create alpha.
4. Postgres is authoritative. Do not add SQLite fallback to the recommendation path.
5. No forced trades. A complete run may end with `NO TRADE` or `NO OPTION`.
6. Maximum three recommendations per signal date across all setup families.
7. Paper risk remains 5% of the configured paper account per recommendation unless the user explicitly changes it.
8. Options expression is exactly one of `long_call`, `call_debit_spread`, or `no_option`. Do not use an equity fallback for an options recommendation.
9. New strategies start `research_only`. Passing a backtest may make them `candidate`; only explicit user approval can make a new strategy paper-eligible.
10. Existing approved-strategy authorization metadata remains immutable and fail-closed.
11. Every external observation carries source, observation timestamp/date, `available_at`, ingestion timestamp, transformation version, and raw/provenance metadata.
12. Backtests join lagged/released data using `available_at <= decision_timestamp`; observation date alone is insufficient.
13. Do not broaden to foreign, OTC, government-risk, manipulated, stale, delisted, leveraged/inverse, or structurally illiquid securities.
14. Routine health output remains local. Discord receives recommendations, meaningful progression, user decisions, or exceptional blockers only.

## 2. Verified starting point

Observed from live Postgres and current code on 2026-08-23:

- `liquid_rs_breakout_close_confirm_1r` is approved for `paper_only_no_live_execution`.
- Latest governed validation: 1,085 historical setups, 63.13% full-sample target hit rate, 68.75% chronological OOS hit rate, 35.94% stop rate, median MFE 1.8539R; gate passed.
- Forward evidence is only one completed paper trade. Do not optimize approved thresholds from that sample.
- Postgres contains 1,278 symbols; 1,238 have at least 495 bars and 1,262 have at least 252 bars.
- The scheduled signal wrapper passes the fixed 34-symbol `CORE_EOD_UNIVERSE`, even though `eod_signals.recommendation_universe_tickers()` already supports broad data-gated selection when tickers are omitted.
- Friday 2026-08-21 catch-up was manually verified against Massive and completed for the 34-symbol core; total Friday price/feature rows rose from 22 to 56.
- The free Massive policy intentionally requests the previous business day. A 16:30 ET run on Friday therefore normally sees Thursday; a next-business-day morning catch-up is required to evaluate Friday before Monday’s session.
- `market_breadth` has only seven forward rows, and the current implementation is not decision-grade: snapshots mark 10,483 active symbols eligible while only 34–56 symbols contribute prices on a given day, yielding 0.32%–0.53% effective coverage. `eligible_count` currently describes joined observations rather than the intended snapshot denominator. Breadth must be relabeled non-actionable until its universe and denominator contract are repaired.
- Sector metadata is sparse: only 531 of 10,483 active reference symbols and 459 of 1,356 active tiered targets have a sector. Sector-dependent gates must fail closed or stay research/context-only when coverage is missing.
- `options_technical_features` has 18,498 rows for the 34-symbol core through 2026-08-20 and is one session behind Friday prices. Freshness must be exact-date gated before an options-volatility evaluation.
- `option_structure_evaluations` has no rows; the selector exists but is not wired into the scheduled lifecycle.
- `earnings_calendar` and `fundamentals` currently have zero rows. The earnings schema has only ticker/date/session/confirmed and lacks source/provenance/availability fields, so absence of a row must mean `event_unknown`, never `no_event`.
- Robinhood MCP authentication/connectivity is healthy, but the server is disabled and configured to expose all discovered tools. No recommendation contains Robinhood enrichment. Any production activation must first replace “all tools” with an explicit read-only allowlist and keep place/cancel/exercise tools unavailable.
- Existing option selector already supports deterministic long calls and call debit spreads with DTE, quote age, spread, open-interest, volume, and conservative-fill gates.
- The repository is heavily dirty and `main` is ahead of `origin/main`; implementation must begin in an isolated clean worktree or after an explicit preservation/cleanup decision.
- Wolfy integration tests currently touch the live database. A dedicated test database/transactional harness is a release prerequisite.

## 3. Target daily architecture

```text
T+1 morning catch-up / paid same-day EOD ingest
    -> session/readiness resolver
    -> point-in-time security eligibility snapshot
    -> broad EOD feature completion
    -> market-regime snapshot
    -> per-strategy gate evaluation for every eligible symbol
         -> pass: deterministic signal
         -> fail: near-miss gate ledger
    -> cross-strategy dedupe + portfolio/correlation allocator
    -> exact read-only option-chain evaluation for finalists only
         -> long call | call debit spread | no option
    -> recommendation writer (max 3, paper only)
    -> paper ledger (no broker action)
    -> outcome reviewer (underlying and option outcomes separated)
    -> concise actionable summary / explicit no-trade reason
```

Core run identity:

```python
DailyEvaluationRun(
    signal_dt,
    decision_timestamp,
    data_cutoff,
    universe_snapshot_id,
    universe_policy_version,
    feature_version,
    strategy_versions,
    source_fingerprints,
    status,
)
```

A run is publishable only when all required stages are complete and read back successfully. Partial data produces `pipeline_incomplete`, never a false clean no-signal result.

## 4. Strategy portfolio design

### 4.1 Existing approved RS breakout — preserve before optimizing

Canonical gates remain unchanged during the parity phase:

- SPY close above its 50-session average.
- Stock’s 20-session return exceeds SPY by at least 2 percentage points.
- Close exceeds the prior five-session high.
- Volume ratio at least 1.2.
- Close above fast average; fast average at or above slow average.
- Risk from entry baseline to prior-low/breakout invalidation no greater than 5%.
- Target 1.0R, maximum hold 10 sessions, close-below-breakout invalidation semantics.

First objective: run the exact approved rule over a broader eligible universe without changing its gate. A golden-parity test must prove identical signals for the original 34 symbols and historical dates.

### 4.2 New research setup A — liquid RS trend pullback/reclaim

Initial hypothesis, subject to the user decision table below:

- U.S. eligible/liquid security with at least 252 bars.
- SPY above 50-session average.
- Stock close above 50- and 200-session averages; 50-session average rising over 20 sessions.
- Positive 20-session excess return versus SPY, initially at least 2 percentage points.
- Pullback lasts 2–7 sessions and touches or approaches the 20-session average within 0.5 ATR without closing below the 50-session average.
- Pullback volume mean no greater than 80% of the preceding 20-session mean.
- Trigger is either a close back above the 20-session average plus prior-session high, or a bullish outside/reclaim close. Test these as predeclared variants, not post-hoc choices.
- Stop is below the pullback swing low with total risk no greater than 5% of entry.
- Initial target 1.5R; maximum hold 10 sessions.
- Near-term earnings/event landmine blocks recommendation but remains visible in near-miss facts.

Do not approve from a single best grid cell. Require chronological walk-forward evidence, stability across neighboring parameters, and low overlap with the approved breakout strategy.

### 4.3 New research setup B — volatility contraction/expansion breakout

Reuse the existing feature contract rather than inventing duplicate indicators:

- Pre-breakout five-session range / 20-session baseline range <= 0.75.
- Current range / pre-breakout range >= 1.50.
- Close-location value >= 0.70.
- Volume percentile >= 0.50.
- Approved RS-breakout shape, SPY trend gate, and sector confirmation.
- Breadth >= 50% above 50DMA may be logged immediately, but cannot become a historically validated hard gate until point-in-time breadth history is adequate.
- Realized volatility and VIX remain context, not arbitrary hard caps.
- Any paper expression is defined-risk options only; no valid chain means `no_option`.

Validate the underlying setup separately from option P&L. Forward option outcomes do not retroactively prove the underlying edge.

### 4.4 Deferred setup — PEAD

Keep `pead` research-only until point-in-time earnings facts include:

- confirmed event date/session,
- actual EPS/revenue,
- contemporaneous consensus/estimate,
- surprise calculation,
- publication timestamp and `available_at`,
- revisions and source provenance.

A current calendar alone is sufficient for an event-risk veto but not for a historical PEAD backtest.

### 4.5 Deprioritized setups

- `sector_cross_sectional_momentum`: keep research-only; current OOS evidence is negative.
- `trend_volume_vol_regime`: keep candidate/research lane; current OOS Sharpe is approximately 0.0584.
- Short setups: defer until long setup/outcome instrumentation is mature.
- Threshold-relaxed clones of the approved breakout: prohibit unless a predeclared hypothesis explains independent economic behavior.

## 5. Universe policy

Create versioned `recommendation_universe_policy_v1` with three stages:

1. Security identity gate:
   - U.S. locale/listing and USD currency;
   - approved security types: common stock and selected unlevered ETFs;
   - active and enabled as of the decision date;
   - exclude OTC, preferreds, warrants, units, rights, leveraged/inverse ETFs, ambiguous tickers, and denylisted risk classes.

2. Data/readiness gate:
   - price and feature row exactly on `signal_dt`;
   - at least 252 bars for daily production and 495 bars for validation-grade analysis;
   - no stale benchmark/sector inputs;
   - no duplicate corporate-action identity.

3. Liquidity/manipulation-risk gate:
   - recommended initial close >= $5;
   - recommended initial 20-session average dollar volume >= $20 million;
   - configurable ETF exception for broad liquid index/sector ETFs;
   - source-backed U.S. identity metadata;
   - deterministic denylist/review list with reason and effective dates.

Roll out in shadow tiers: 100 -> 200 -> recommended 300 -> optional 400. Promote only after coverage, runtime, and signal-quality checks pass. Do not jump directly to all 1,238 depth-ready symbols.

## 6. Near-miss and observability contract

Every `(run_id, signal_dt, ticker, strategy_version)` receives exactly one terminal evaluation row:

```sql
CREATE TABLE setup_gate_evaluations (
  id bigserial PRIMARY KEY,
  run_id bigint NOT NULL REFERENCES daily_evaluation_runs(id),
  signal_dt date NOT NULL,
  ticker text NOT NULL,
  strategy_id int NOT NULL REFERENCES strategies(id),
  strategy_version text NOT NULL,
  passed boolean NOT NULL,
  terminal_reason text NOT NULL,
  failed_gates jsonb NOT NULL DEFAULT '[]'::jsonb,
  gate_facts jsonb NOT NULL,
  deterministic_score numeric,
  source_fingerprint text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(run_id, ticker, strategy_id)
);
```

Canonical reason codes include:

- `passed`
- `missing_current_price`
- `missing_current_features`
- `insufficient_history`
- `security_ineligible`
- `liquidity_failed`
- `market_regime_failed`
- `trend_failed`
- `breakout_not_confirmed`
- `pullback_shape_failed`
- `relative_strength_failed`
- `volume_failed`
- `stop_risk_too_wide`
- `overextended`
- `breadth_unavailable`
- `breadth_failed`
- `sector_confirmation_failed`
- `event_landmine`
- `option_chain_missing`
- `option_liquidity_failed`
- `portfolio_correlation_block`
- `daily_limit_block`

Store all failed gates, not just the first, but designate one deterministic terminal reason for aggregation. Daily and rolling reports must show gate attrition counts without changing thresholds automatically.

## 7. Validation and promotion policy

For each new setup family:

1. Freeze hypothesis, feature definitions, parameters, costs, universe policy, entry convention, gap treatment, and outcome semantics before testing.
2. Use chronological train/validation/test or anchored expanding walk-forward splits; never random split market time series.
3. Purge fold boundaries by at least the maximum holding horizon and preserve an untouched final 15%–20% holdout that is opened once.
4. Preserve the currently approved strategy’s immutable 100-total/25-OOS authorization gate. For new families, recommended research viability is at least 200 total signals, 75 strictly OOS signals, and 30 unique signal dates; recommended candidate evidence is at least 500 total, 150 aggregate walk-forward OOS signals, and 50 OOS unique signal dates. Smaller samples remain explicitly experimental shadow research.
5. Apply conservative stop-first handling when stop and target occur in the same daily bar. A gap through the stop exits at the next available open, not the modeled stop price; unresolved missing/delisting bars are never wins.
6. Keep the EOD close as a continuity/reference outcome, but require every new setup to remain acceptable using next-session-open entry with conservative gap and slippage handling. A setup that works only at an unattainable closing fill cannot be promoted.
7. Include slippage and commissions; option structures use conservative quote-side fills.
8. Report hit rate, OOS hit rate, stop rate, cost-adjusted expectancy in R, MFE/MAE and tail-loss distributions, drawdown, turnover, holding period, unique tickers/dates, same-day clustering, regime/sector concentration, and overlap with existing setups. Confidence intervals must be clustered by signal date.
9. Record every attempted parameter family in `research_log`; do not report only winners.
10. Control multiple testing with preregistered economically motivated variants, limited family count, Holm adjustment for promotion claims, and neighborhood stability checks. Exploratory secondary analysis must be labeled and kept out of approval claims.
11. Run sensitivity tests around each chosen threshold and compare against simple baselines.
12. Reject strategies dependent on one ticker, sector, month, regime, or single walk-forward fold.
13. Candidate status is automatic only if the governed gate allows it; approval always requires explicit user authorization.
14. Start a minimum forward shadow/paper observation window before considering approval. Recommended first review: 30 closed outcomes; meaningful continuation decision: 60 outcomes per setup. Do not use a calendar shortcut.

## 8. Cross-strategy allocation

Create one deterministic allocator after all strategy evaluators finish:

- rank within strategy using documented setup facts;
- normalize scores to avoid one strategy’s scale dominating;
- deduplicate the same ticker across strategies;
- enforce global maximum three recommendations;
- block excessive existing position exposure;
- initially allow no more than one new recommendation per sector per day;
- block pairs with trailing 60-session return correlation above a configured threshold (recommended 0.80) unless the higher-ranked candidate replaces the lower;
- measure setup-family dependence separately using simultaneous signal-date overlap and date-clustered realized R outcomes; ticker-return correlation alone is not evidence that two strategies are orthogonal;
- preserve multi-label setup research when one ticker qualifies for several families, but execute at most one deduplicated position for that ticker;
- preserve `NO TRADE` when all candidates fail portfolio constraints;
- log blocked candidates and reasons.

Do not optimize the allocator against the same data used to discover setup rules.

## 9. Data roadmap

### Required now

- Complete Massive T+1 core/broad price and feature catch-up before signal generation.
- Security master fields: locale, primary exchange, market, security type, currency, active dates, source, available-at/provenance.
- Daily point-in-time universe snapshots with separate `reference_universe`, `research_universe`, `daily_signal_universe`, and `breadth_universe` identities.
- Market breadth only from the valid stable breadth snapshot, with `snapshot_eligible_count`, `observed_count`, `missing_count`, `coverage_fraction`, `unchanged_count`, `universe_snapshot_id`, `available_at`, and `quality_status`. Require at least 95% coverage before breadth is publishable, and never carry a stale value forward as current.
- Exact earnings dates for event veto, with provenance and availability.
- Candidate-only read-only option chains.

### Add after core rollout

- Point-in-time earnings actual/estimate/surprise data for PEAD if a valid source is selected.
- Historical constituents/membership from a licensed or otherwise defensible source; do not fabricate historical snapshots from today’s universe.
- Corporate-action identity mapping.
- Sector membership history where available.

### Context, not automatic alpha

- VIX, Treasury curve, Cboe aggregate put/call, FINRA reported short volume, Nasdaq short interest.
- These must remain correctly named and availability-lagged. FINRA short-sale volume is not outstanding short interest and not consolidated whole-market short volume.
- Existing Nasdaq short-interest history that assigns one retrieval date as `available_at` for older periods must be quarantined as a current backfill/snapshot, not treated as point-in-time historical evidence. Future observations require actual dissemination timestamps.

## 10. Daily scheduling design

### Free Massive/T+1 mode (recommended immediate default)

- 05:30 ET every day, including weekends: resolve the latest exchange session expected to be available under the free entitlement and perform a no-write availability probe. If no newer completed session is available, exit silently.
- 05:40–06:00: sharded catch-up for the target session, retry only missing symbols. Weekend runs may collect Friday as soon as the provider exposes it; do not intentionally wait until Monday.
- 06:05: exact-date readiness check; require 34/34 core/benchmark coverage and the configured broad-universe coverage threshold.
- 06:10: compute standard and options technical features.
- 06:15: freeze universe membership and compute breadth only when the repaired breadth coverage gate passes.
- 06:20: ingest/refresh market-structure and event data; unknown event status remains unknown.
- 06:30: deterministic strategy evaluations, near misses, and approved qualifiers.
- 06:40: candidate-only event/chain enrichment and option selection.
- 06:50: recommendation writer, paper logger, and outcome reviewer.
- 07:30: optional explicitly allowlisted Robinhood read-only broker-context refresh.
- 07:45: pre-open invalidation/event check.
- 08:00: concise delivery if actionable or if an exceptional blocker requires the user; always name the signal date.
- 12:00: silent bounded repair for failed non-price auxiliary feeds.
- Existing 16:30 jobs may remain as an early health/research pass, but under T+1 they must not be labeled as evaluating that same day’s close and publication must wait for a readiness-complete run.

### Paid/current-day mode

If the user buys a provider entitlement verified to expose same-session completed aggregates, move the same chain after market close. Do not set `WOLFY_MASSIVE_ALLOW_CURRENT_DAY=1` without a verified entitlement test.

## 11. Implementation tasks

### Task 1: Preserve the current workspace and create an isolated implementation worktree

**Objective:** Prevent the large pre-existing dirty tree from contaminating implementation or commits.

**Files:** No production files. Operational git worktree only.

**Steps:**
1. Record `git status --short --branch`, `git diff --stat`, current branch, and untracked inventory.
2. Do not stash, reset, clean, or delete user work without explicit scope confirmation.
3. Fetch `origin/main` and create a dedicated worktree/branch such as `wolfy/daily-multi-setup-evaluator` from the agreed base.
4. Verify the new worktree is clean.
5. Run a staged secret-scan baseline before every future commit; never use `git add .`.

**Verification:** Clean isolated worktree; original dirty workspace unchanged byte-for-byte.

### Task 2: Create a dedicated Postgres test database harness

**Objective:** Stop new integration tests from mutating live Wolfy state.

**Files:**
- Create: `/root/.hermes/wolfy/test_db.py`
- Create: `/root/.hermes/wolfy/test_test_db.py`
- Modify: `/root/.hermes/wolfy/postgres_init.sql`
- Modify during the corresponding feature tasks: `/root/.hermes/wolfy/test_eod_signals.py`, `/root/.hermes/wolfy/test_orchestration_runner.py`, `/root/.hermes/wolfy/test_eod_backtest.py`, `/root/.hermes/wolfy/test_eod_monitoring.py`, `/root/.hermes/wolfy/test_recommendation_outcome_review.py`, and the experimental-options tests, replacing live-DB fixtures with the isolated harness.

**RED:** A test must fail if `WOLFY_TEST_POSTGRES_DSN` resolves to database `wolfy` or if a production-like DSN is used without an explicit isolated transaction fixture.

**GREEN:** Add a fixture that provisions/validates `wolfy_test`, applies schema idempotently, wraps each test in rollback where possible, and exposes unique future-dated fixture helpers.

**Verification:** Focused harness tests pass; production approved strategy and counts are identical before/after the test run.

**Commit:** `test(wolfy): isolate Postgres integration tests`

### Task 3: Add daily run and gate-evaluation schema

**Objective:** Make every daily evaluation auditable and idempotent.

**Files:**
- Modify: `/root/.hermes/wolfy/postgres_init.sql`
- Create: `/root/.hermes/wolfy/daily_evaluation_ledger.py`
- Create: `/root/.hermes/wolfy/test_daily_evaluation_ledger.py`

**RED:** Test unique run identity, legal status transitions, one gate row per run/ticker/strategy, canonical reason validation, JSON provenance, ingestion-manifest row counts/hashes, and idempotent rerun.

**GREEN:** Add `daily_evaluation_runs`, `ingestion_run_manifests`, `setup_gate_evaluations`, and indexes. Statuses: `started`, `data_incomplete`, `evaluated`, `published`, `failed`. Prevent `published` without complete required stage metadata. Each ingestion manifest records dataset, target session, provider/source endpoint, entitlement and delay class, started/completed timestamps, expected/received symbol and row counts, retry/status, raw-payload hash or immutable object reference, parser/schema version, and quality-gate result. Derived-stage metadata records input session, computed/available timestamps, transformation version, source run IDs/input hash, and universe snapshot ID.

**Verification:** Migration runs twice cleanly; invalid transitions fail closed; no live rows touched.

**Commit:** `feat(wolfy): add auditable daily evaluation ledger`

### Task 4: Add a session resolver and readiness gate

**Objective:** Determine the intended signal date and prohibit partial publication.

**Files:**
- Create: `/root/.hermes/wolfy/eod_readiness.py`
- Create: `/root/.hermes/wolfy/test_eod_readiness.py`
- Modify: `/root/.hermes/wolfy/orchestration_runner.py`

**RED:** Cover weekdays, weekends, holidays/calendar fallback, free T+1 mode, paid-current-day mode, missing benchmark, partial universe, stale features, and future dates.

**GREEN:** Return a typed readiness result with expected session, latest complete session, coverage numerator/denominator, missing symbols, source mode, and publishable flag. Use a pinned NYSE session calendar implementation or an explicitly versioned local calendar table; weekend-only arithmetic is not sufficient for exchange holidays and special closures.

**Verification:** Friday data resolves on Monday pre-open in free mode; Friday after-close remains incomplete until provider availability is verified. Holiday and special-closure fixtures resolve to the correct prior completed session.

**Commit:** `feat(wolfy): fail closed on incomplete EOD readiness`

### Task 5: Build versioned security identity and eligibility metadata

**Objective:** Enforce U.S./liquidity/risk exclusions before strategy evaluation.

**Files:**
- Create: `/root/.hermes/wolfy/security_master.py`
- Create: `/root/.hermes/wolfy/test_security_master.py`
- Modify: `/root/.hermes/wolfy/postgres_init.sql`
- Modify: `/root/.hermes/wolfy/wolfy_tiered_universe.py` only where shared metadata belongs.

**RED:** Test U.S. common stock, approved broad ETF, foreign locale, OTC, leveraged/inverse ETF, warrant/unit/right, inactive symbol, missing identity, and effective-date changes.

**GREEN:** Add source-backed security metadata and a deterministic eligibility decision with canonical exclusion reasons and effective dates.

**Verification:** Unknown/ambiguous identity fails closed; user denylist always wins; no current active symbol is silently reclassified.

**Commit:** `feat(wolfy): add point-in-time security eligibility gate`

### Task 6: Extract the broad recommendation universe policy

**Objective:** Replace the cron-only 34-symbol scope with a controlled versioned eligible universe.

**Files:**
- Create: `/root/.hermes/wolfy/recommendation_universe.py`
- Create: `/root/.hermes/wolfy/test_recommendation_universe.py`
- Modify: `/root/.hermes/wolfy/eod_signals.py:267-297`
- Modify: `/root/.hermes/wolfy/orchestration_config.py`

**RED:** Test exact-date prices/features, 252/495-bar tiers, minimum price, average dollar volume, U.S. identity, ETF policy, stale rows, deterministic sort, cap, and reason output.

**GREEN:** Return both selected symbols and exclusions. Add shadow caps 100/200/300/400 and a versioned policy fingerprint.

**Verification:** Original 34 are preserved when eligible; broad list contains no blocked security class; identical inputs produce identical output/fingerprint.

**Commit:** `feat(wolfy): version broad daily recommendation universe`

### Task 7: Golden-parity adapter for the approved breakout

**Objective:** Preserve the approved strategy exactly while changing evaluation architecture.

**Files:**
- Create: `/root/.hermes/wolfy/setup_evaluators.py`
- Create: `/root/.hermes/wolfy/test_setup_evaluators.py`
- Modify: `/root/.hermes/wolfy/eod_signals.py:426-715`

**RED:** Build golden fixtures for known pass/fail cases and compare old/new approved breakout signals and raw facts on the 34-symbol core across representative historical sessions.

**GREEN:** Implement `SetupEvaluation` and an approved-breakout evaluator that emits all gate facts/reasons. Keep the existing signal JSON contract.

**Verification:** Zero signal drift on the parity window; only the new near-miss ledger differs.

**Commit:** `refactor(wolfy): expose approved breakout gate evaluations`

### Task 8: Persist near misses and gate attrition

**Objective:** Explain why every eligible ticker did or did not qualify.

**Files:**
- Create: `/root/.hermes/wolfy/near_miss_analytics.py`
- Create: `/root/.hermes/wolfy/test_near_miss_analytics.py`
- Modify: `/root/.hermes/wolfy/setup_evaluators.py`
- Modify: `/root/.hermes/wolfy/daily_evaluation_ledger.py`

**RED:** Test all canonical reason codes, multi-failure ordering, one deterministic terminal reason, no duplicate rows, rolling aggregation, and no threshold mutation.

**GREEN:** Persist gate rows and generate 1/5/20/60-session attrition summaries.

**Verification:** Sum of pass plus fail evaluations equals eligible universe x active evaluated strategies.

**Commit:** `feat(wolfy): record deterministic setup near misses`

### Task 9: Add market-regime snapshots as context-first features

**Objective:** Create reproducible broad/narrow/chop/risk-off labels without prematurely hard-gating setups.

**Files:**
- Create: `/root/.hermes/wolfy/market_regime.py`
- Create: `/root/.hermes/wolfy/test_market_regime.py`
- Modify: `/root/.hermes/wolfy/postgres_init.sql`
- Reuse: `/root/.hermes/wolfy/free_technical_data.py`

**RED:** Test missing breadth, stale VIX, SPY/QQQ/IWM disagreement, broad risk-on, narrow risk-on, neutral/chop, and risk-off/high-volatility cases. Verify `available_at` prevents lookahead.

**GREEN:** Store regime facts and version, with `insufficient_data` as a valid label. Initially attach to evaluations/reports only.

**Verification:** Replaying the same decision timestamp produces the same regime.

**Commit:** `feat(wolfy): add point-in-time market regime snapshots`

### Task 10: Repair breadth semantics, then accumulate/backfill only defensible history

**Objective:** Replace the current 10,483-symbol/34–56-observation denominator mismatch with a stable point-in-time breadth contract before increasing breadth history.

**Files:**
- Create: `/root/.hermes/wolfy/breadth_backfill.py`
- Create: `/root/.hermes/wolfy/test_breadth_backfill.py`
- Modify: `/root/.hermes/wolfy/free_technical_data.py`
- Modify: `/root/.hermes/wolfy/postgres_init.sql`

**RED:** Reproduce the current false-denominator case and require it to return `quality_status='insufficient_coverage'`. Test separate snapshot/observed/missing counts, coverage fraction, changing membership, unchanged count, sector-metadata gaps, stale data, and rejection of historical dates without a valid membership snapshot. Test licensed/sourced membership input with `available_at` and transformation version.

**GREEN:** Define an explicit stable `breadth_universe`; persist `snapshot_eligible_count`, `observed_count`, `missing_count`, `coverage_fraction`, `unchanged_count`, `universe_snapshot_id`, `available_at`, and `quality_status`; require at least 95% coverage before breadth is publishable. Support forward accumulation immediately and historical backfill only from an explicit valid membership source.

**Verification:** Existing seven rows are relabeled/non-actionable unless they satisfy the repaired contract; no row is labeled broad or point-in-time when derived from current membership or sub-threshold coverage; provenance audit passes; breadth-dependent setup gates fail closed rather than carry forward or substitute zero.

**Commit:** `fix(wolfy): repair and backfill provenance-safe breadth`

### Task 11: Implement trend pullback/reclaim research evaluator

**Objective:** Add an orthogonal research-only setup for non-breakout trend continuation.

**Files:**
- Modify: `/root/.hermes/wolfy/eod_signals.py` strategy seed only
- Modify: `/root/.hermes/wolfy/setup_evaluators.py`
- Create: `/root/.hermes/wolfy/test_trend_pullback_strategy.py`

**RED:** One behavior per test: trend stack, rising 50DMA, RS threshold, pullback duration, 20DMA/ATR proximity, 50DMA breach, volume contraction, reclaim trigger variants, stop risk, event veto, and deterministic raw facts.

**GREEN:** Seed `liquid_rs_trend_pullback_reclaim_v1` as `research_only`; produce evaluations/signals but no actionable setups/recommendations.

**Verification:** No row can become paper-eligible from seeding or backtest alone.

**Commit:** `feat(wolfy): add research-only trend pullback evaluator`

### Task 12: Build setup-native pullback backtest and governed report

**Objective:** Evaluate the new setup using its actual entry/stop/target semantics.

**Files:**
- Modify: `/root/.hermes/wolfy/eod_backtest.py`
- Create: `/root/.hermes/wolfy/test_trend_pullback_backtest.py`
- Modify: `/root/.hermes/wolfy/eod_monitoring.py` only after gate format is frozen.

**RED:** Test chronological OOS split, stop-first same-bar handling, target 1.5R, 10-session horizon, costs, holdout preservation, parameter-attempt ledger, and immutable gate normalization.

**GREEN:** Add a named validation mode/version and persist backtests/research log. Passing means candidate at most.

**Verification:** Full report includes concentration, overlap, sensitivity, and failure reasons; rerun is reproducible.

**Commit:** `feat(wolfy): validate trend pullback setup outcomes`

### Task 13: Complete volatility-contraction underlying validation

**Objective:** Turn the existing research feature into an auditable underlying setup study.

**Files:**
- Modify: `/root/.hermes/wolfy/setup_evaluators.py`
- Modify: `/root/.hermes/wolfy/eod_backtest.py`
- Modify: `/root/.hermes/wolfy/test_options_volatility_strategy.py`
- Modify: `/root/.hermes/wolfy/test_free_technical_data.py`

**RED:** Test contraction/expansion/CLV/volume rules, missing breadth as context versus hard gate by version, sector confirmation, target/stop semantics, and high-volatility context.

**GREEN:** Separate `underlying_setup_passed` from `option_structure_selected`; never infer option success from equity outcome.

**Verification:** Research report can be reproduced without any option chain; no strategy auto-approval.

**Commit:** `feat(wolfy): validate volatility-contraction underlying setup`

### Task 14: Strengthen earnings/event provenance and vetoes

**Objective:** Make event risk fail-closed and prepare, but do not prematurely activate, PEAD.

**Files:**
- Create: `/root/.hermes/wolfy/event_data.py`
- Create: `/root/.hermes/wolfy/test_event_data.py`
- Modify: `/root/.hermes/wolfy/postgres_init.sql`
- Modify: `/root/.hermes/wolfy/eod_signals.py:166-176,792-802`
- Modify: `/root/.hermes/wolfy/eod_monitoring.py:223-255`

**RED:** Test source/available-at, BMO/AMC session semantics, revisions, conflicting sources, unconfirmed dates, missing data, hold-window overlap, and historical no-lookahead joins.

**GREEN:** Extend or replace the calendar with source-versioned event observations. Current reliable dates drive vetoes. Surprise fields remain nullable and PEAD stays research-only until sufficient sourced history exists.

**Verification:** A recommendation cannot silently treat unknown event data as confirmed safe when policy says fail closed.

**Commit:** `feat(wolfy): add point-in-time earnings event contract`

### Task 15: Add PEAD only after source acceptance

**Objective:** Implement a valid earnings-drift study if and only if point-in-time actual/estimate data exists.

**Files:**
- Modify: `/root/.hermes/wolfy/event_data.py`
- Modify: `/root/.hermes/wolfy/setup_evaluators.py`
- Create: `/root/.hermes/wolfy/test_pead_strategy.py`
- Modify: `/root/.hermes/wolfy/eod_backtest.py`

**Gate:** This task is blocked pending user selection of a data source and a provenance audit.

**RED/GREEN:** Test announcement-session alignment, surprise calculation, next tradable EOD decision, liquidity, drift horizon, and revision availability. No source means no implementation shortcut.

**Verification:** Historical joins prove each estimate and actual was available by decision time.

**Commit:** `feat(wolfy): add provenance-safe PEAD research setup`

### Task 16: Unify exact read-only option-chain acquisition

**Objective:** Fetch chains only for finalists and normalize Cboe/Robinhood data into one contract.

**Files:**
- Create: `/root/.hermes/wolfy/option_chain_provider.py`
- Create: `/root/.hermes/wolfy/test_option_chain_provider.py`
- Reuse: `/root/.hermes/wolfy/cboe_delayed_options.py`
- Reuse: `/root/.hermes/wolfy/robinhood_broker_enrichment.py`
- Modify: `/root/.hermes/wolfy/run_experimental_options_forward_test.py`

**RED:** Test source priority, exact quote timestamps, stale chains, missing OI/volume, nonstandard contracts, DTE, symbol normalization, source failure, and absence of any broker-write method. Add a configuration test that fails if the evaluator’s Robinhood MCP exposure is `all` or contains place/cancel/replace/exercise/money-movement tools.

**GREEN:** Produce normalized read-only chain snapshots with source fingerprint. Fetch only after underlying and portfolio gates reduce the candidate set. Keep Cboe delayed as the default research source; Robinhood remains optional broker-context validation and may be enabled only after an explicit read-only tool allowlist is installed.

**Verification:** No place/cancel/exercise tool exists in the evaluator adapter or MCP allowlist; source outage returns unavailable/no-option without signal mutation. Persist tool/source name, retrieval timestamp, response identifier/hash, and normalized warnings.

**Commit:** `feat(wolfy): normalize read-only option chains`

### Task 17: Enforce long call / call spread / no-option decisions

**Objective:** Remove ambiguous equity fallback semantics from the options recommendation path.

**Files:**
- Modify: `/root/.hermes/wolfy/options_structure_selector.py`
- Modify: `/root/.hermes/wolfy/experimental_options_pipeline.py`
- Modify: `/root/.hermes/wolfy/eod_signals.py` recommendation notes/types
- Modify: `/root/.hermes/wolfy/test_options_structure_selector.py`
- Modify: `/root/.hermes/wolfy/test_experimental_options_pipeline.py`
- Modify: `/root/.hermes/wolfy/test_experimental_options_recommendations.py`

**RED:** Test deterministic choice, no valid chain, unaffordable one-contract max loss, target below break-even, stale quote, tie-breaking, max-loss sizing, and explicit `no_option` reason.

**GREEN:** Output a stock-specific long call, call debit spread, or `no_option`; never substitute equity. Keep underlying setup reporting separate.

**Verification:** Every option recommendation has exact legs, quote timestamp, fill model, max loss, target-state value, policy version, `paper_only=true`, `no_live_execution=true`, and `broker_order_submitted=false`.

**Commit:** `feat(wolfy): enforce deterministic no-equity-fallback option selection`

### Task 18: Add cross-strategy portfolio allocator

**Objective:** Apply one global max-three, correlation, sector, heat, and duplicate gate.

**Files:**
- Create: `/root/.hermes/wolfy/portfolio_allocator.py`
- Create: `/root/.hermes/wolfy/test_portfolio_allocator.py`
- Modify: `/root/.hermes/wolfy/orchestration_runner.py`

**RED:** Test same ticker from two strategies, score normalization, sector collision, correlation collision, existing exposure, max heat, max-three, deterministic ties, and all-blocked no-trade.

**GREEN:** Return selected and blocked candidates with reason codes. Strategy evaluators cannot bypass it.

**Verification:** No run creates more than three recommendation rows across all strategies.

**Commit:** `feat(wolfy): allocate daily candidates across strategies`

### Task 19: Separate underlying and option outcome ledgers

**Objective:** Learn from technical setup quality and option expression quality independently.

**Files:**
- Modify: `/root/.hermes/wolfy/recommendation_outcome_review.py`
- Create: `/root/.hermes/wolfy/option_outcome_review.py`
- Create: `/root/.hermes/wolfy/test_option_outcome_review.py`
- Modify: `/root/.hermes/wolfy/postgres_init.sql`

**RED:** Test untriggered setup, target/stop/time exit, split/corporate-action handling, option mark availability, expiration, max loss, spread value, stale marks, and idempotent closure.

**GREEN:** Keep `recommendation_outcomes` for the underlying and create an option-specific ledger linked to `option_structure_evaluations` and recommendation/trade IDs.

**Verification:** Option P&L cannot alter the approved underlying strategy’s gate unless a separately versioned governance rule explicitly permits it.

**Commit:** `feat(wolfy): track option and underlying outcomes separately`

### Task 20: Build one idempotent daily orchestrator

**Objective:** Replace loosely coupled publication timing with one readiness-aware state machine.

**Files:**
- Create: `/root/.hermes/wolfy/daily_evaluation.py`
- Create: `/root/.hermes/wolfy/test_daily_evaluation.py`
- Modify: `/root/.hermes/wolfy/orchestration_runner.py`
- Create: `/root/.hermes/scripts/wolfy_daily_evaluation.py`

**RED:** Test complete run, partial data, retry, duplicate invocation, stage failure, broad shadow mode, no qualifiers, option-source failure, and zero broker actions.

**GREEN:** Execute stages in the target order, persist each stage, and publish only after read-back verification. Support `--dry-run`, `--shadow`, `--signal-dt`, `--universe-cap`, and `--strategy` scope.

**Verification:** Rerunning an identical date/fingerprint creates no duplicate recommendations, trades, option evaluations, or gate rows.

**Commit:** `feat(wolfy): orchestrate fail-closed daily setup evaluation`

### Task 21: Add actionable summaries and no-trade semantics

**Objective:** Distinguish recommendations, clean no-signal, portfolio block, no-option, and pipeline incomplete.

**Files:**
- Modify: `/root/.hermes/wolfy/recommendation_engine_daily_summary.py`
- Modify: `/root/.hermes/wolfy/test_recommendation_engine_daily_summary.py`
- Modify: `/root/.hermes/wolfy/wolfy_report_context.py`

**RED:** Test all five states, near-miss top reasons, source date, strategy/version, entry/stop/target, option decision, risk, and concise formatting.

**GREEN:** Emit empty output for routine success with no user-relevant change if delivery policy requires silence; otherwise explicit concise `NO TRADE` only from a complete run.

**Verification:** A partial run can never be labeled “no qualifying setup.”

**Commit:** `feat(wolfy): report trustworthy daily recommendation state`

### Task 22: Add T+1 morning catch-up cron and readiness-triggered sequencing

**Objective:** Evaluate every completed trading session before the next open without requiring same-day paid data.

**Files:**
- Modify: `/root/.hermes/cron/jobs.json` through `cronjob` management, not manual ID guessing
- Reuse/modify wrappers under `/root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_*.py`
- Create/modify: `/root/.hermes/scripts/wolfy_daily_evaluation.py`
- Modify: `/root/.hermes/wolfy/test_orchestration_runner.py`

**RED:** Simulate Friday->Monday, holiday, delayed shard, one missing symbol, retry success, and permanent provider failure.

**GREEN:** Add bounded morning catch-up, then invoke daily evaluation only when readiness passes. Keep routine output local.

**Verification:** Cron list/readback shows exact schedules, scripts, delivery policy, and no duplicate publisher. Manual scoped smoke proves Friday data can be evaluated Monday pre-open.

**Commit:** `ops(wolfy): schedule T+1 daily evaluation chain`

### Task 23: Shadow rollout of expanded universe

**Objective:** Measure quality and runtime before expanded symbols can create recommendations.

**Files:**
- Configuration only through versioned policy/config rows and approved wrapper arguments.
- Create: `/root/.hermes/wolfy/shadow_rollout_report.py`
- Create: `/root/.hermes/wolfy/test_shadow_rollout_report.py`

**Steps:**
1. Run 100-symbol shadow for at least five complete sessions.
2. Verify >=99% expected-date coverage, no blocked security classes, deterministic reruns, runtime budget, and parity on original 34.
3. Advance to 200, then recommended 300, only when the prior tier passes.
4. Compare pass rate, gate attrition, sector concentration, duplicate rate, and setup overlap.
5. Do not relax gates to hit a recommendation quota.

**Verification:** Signed/read-back rollout report per tier; no shadow signal creates paper rows.

**Commit:** `feat(wolfy): report expanded-universe shadow rollout`

### Task 24: Enable broad approved-breakout production

**Objective:** Allow the unchanged approved setup to create paper recommendations from the accepted broad universe.

**Files:**
- Modify: `/root/.hermes/scripts/wolfy_eod_features_signals.py`
- Modify: `/root/.hermes/wolfy/orchestration_runner.py`
- Modify: `/root/.hermes/wolfy/test_orchestration_runner.py`

**RED:** Prove omitted/default tickers select the accepted versioned universe, explicit ticker replay remains available, max-three is global, and explicit approval metadata is required.

**GREEN:** Switch production only after shadow acceptance. Preserve core-universe emergency scope as an explicit flag, not the default.

**Verification:** Scoped dry-run, live paper-only smoke, idempotent rerun, database readback, no broker orders.

**Commit:** `feat(wolfy): evaluate approved breakout across eligible universe`

### Task 25: Research/paper rollout for new setups

**Objective:** Introduce new setup families without contaminating approved results.

**Steps:**
1. Trend pullback: research signals -> governed backtest -> candidate -> forward shadow -> user approval decision -> paper only.
2. Volatility contraction: underlying research validation -> forward exact-chain option paper experiment -> separate option outcomes -> user approval decision if warranted.
3. PEAD: remain blocked until source/provenance acceptance.
4. Never pool setup outcomes for promotion; report correlations and overlap separately.

**Verification:** Strategy table status/metadata readback; only explicitly paper-approved setup IDs feed the approved recommendation writer.

### Task 26: Full review, release, and post-release canary

**Objective:** Deliver a reviewed, reversible, observable release.

**Steps:**
1. Run focused tests after each RED/GREEN cycle.
2. Run relevant file suites, then full isolated test suite.
3. Run migration idempotency and secret scan.
4. Request independent spec-compliance review.
5. Fix findings; if staged diff changes, request fresh review.
6. Request independent code-quality/security review.
7. Stage only reviewed files; commit in bounded commits; push branch.
8. Run serialized live paper-only canary after all tests/reviews finish.
9. Verify DB state and Git remote separately.
10. Maintain rollback commands/config for universe cap and publisher.

**Release gates:**
- zero broker-write capability;
- no more than three recommendations/day;
- exact paper/no-live metadata;
- data readiness complete;
- universe exclusions verified;
- strategy parity verified;
- idempotent rerun;
- actionable summary correct;
- cron readback correct;
- no production test fixtures remain.

## 12. User decisions and recommended defaults

These are the places where the user’s judgment materially changes design or cost.

### Decision A: Data latency versus provider cost

- **Recommended immediate default:** keep free Massive T+1 and run the complete evaluation before the next open.
- Alternative: pay for verified same-session completed EOD data and publish after close.
- User input needed: whether same-evening recommendations justify a recurring provider cost, and the acceptable monthly budget.

### Decision B: Expanded universe size

- **Recommended:** staged 100 -> 200 -> 300; stop at 300 initially.
- Alternative: 400 after evidence.
- User input needed: preference for broader opportunity frequency versus simpler oversight. Quality gates do not change with size.

### Decision C: ETF inclusion

- **Recommended:** allow unlevered broad/sector ETFs but place them in a separate sleeve; exclude leveraged/inverse/single-stock ETFs.
- User input needed: whether ETF recommendations should count toward the same max-three (recommended yes) and whether more than one ETF may appear per day (recommended one).

### Decision D: Pullback target and trigger

- **Recommended research defaults:** 1.5R target, 10-session maximum hold; test two predeclared reclaim triggers separately.
- User input needed before freezing the hypothesis: prioritize more frequent earlier reclaims or stricter confirmation with fewer signals.

### Decision E: Sector/correlation concentration

- **Recommended:** one new recommendation per sector per day and block >0.80 trailing-60-session correlation, selecting the higher-ranked candidate.
- User input needed: whether this is too restrictive for concentrated leadership markets.

### Decision F: Earnings data/PEAD

- **Recommended:** use free/current reliable dates for event veto now; defer PEAD until a point-in-time historical actual/estimate source is selected.
- User input needed: whether PEAD is important enough to pay for licensed historical estimates/surprises.

### Decision G: Experimental options liquidity

- Existing selector defaults: 7–35 DTE, minimum OI 25 or volume 10, maximum relative spread 25%, quote age <=30 minutes.
- **Recommended:** retain these for initial paper collection; review after 30 completed option observations, not before.
- User input needed: whether to make spreads stricter (for example 15–20%) at the cost of more `no_option` results.

### Decision H: New-strategy approval threshold

- **Recommended:** governed historical gate plus at least 30 closed forward outcomes for the first formal review and 60 closed outcomes per setup for a meaningful continuation/approval decision. Historical candidate evidence should normally meet 500 total and 150 aggregate walk-forward OOS signals; smaller samples remain explicitly experimental shadow research.
- User input needed: whether the forward evidence floor should be higher. It should not be lower without a documented provisional-experiment exception.

### Decision I: Total portfolio heat

- The standing policy is 5% paper risk per recommendation with a maximum of three recommendations per day. Three simultaneous full-risk positions imply up to 15% initial portfolio heat before accounting for existing positions.
- **Recommended:** keep 5% per trade, cap aggregate open paper heat at 15%, and allow fewer than three recommendations whenever existing heat leaves insufficient capacity. Never scale a setup above 5% to use unused heat.
- User input needed: whether 15% aggregate paper heat is acceptable or whether the system should use a stricter cap such as 10%, which would frequently limit the portfolio to two full-risk positions.

### Decision J: Daily data coverage threshold

- **Recommended:** require 100% freshness for SPY, QQQ, IWM, and every sector benchmark used by a gate; require at least 99% freshness for the accepted recommendation universe; explicitly record excluded/missing symbols and prohibit breadth from claiming full-universe coverage when the threshold is missed.
- User input needed: whether broad-universe publication should require 100% coverage. A 100% rule is simpler but lets one provider/symbol defect block the entire day.

### Decision K: Implementation budget gate

- The deterministic optimizer gate currently reports token usage above its configured daily cap. This plan does not bypass that safeguard.
- **Recommended:** allow operational EOD catch-up/recommendation runs to continue, but begin broad code implementation after the budget window resets. If the user wants immediate implementation despite the cap, require an explicit one-session override with a fixed task/turn ceiling rather than weakening or disabling the permanent guardian.
- User input needed: wait for the normal reset, or authorize a bounded one-session implementation override after the plan is accepted.

### Decision L: Unknown earnings/event status

- The current earnings table is empty, so “no row” cannot mean “no earnings.”
- **Recommended:** withhold final single-stock delivery when event status is unknown inside the planned holding window; retain the deterministic underlying signal as non-actionable evidence with `EVENT_UNKNOWN`. ETFs are exempt from issuer-earnings gating. Once a trustworthy source exists, confirmed clear status may pass normally.
- User input needed: retain the recommended fail-closed behavior or use warning-only behavior. Fail-closed is safer but will reduce recommendation frequency until event coverage is reliable.

## 13. Suggested execution phases

### Phase 0 — safety foundation
Tasks 1–4. Isolated worktree, test DB, run ledger, readiness.

### Phase 1 — broaden without changing alpha
Tasks 5–10 and 23–24. Security master, controlled universe, parity adapter, near misses, regime context, breadth provenance, shadow rollout, broad approved setup.

### Phase 2 — add orthogonal setups
Tasks 11–13. Pullback/reclaim and volatility-contraction underlying validation.

### Phase 3 — event and options completeness
Tasks 14–19. Event contract, optional PEAD, normalized chains, no-equity-fallback option selection, allocator, separate outcomes.

### Phase 4 — daily automation and release
Tasks 20–22, 25–26. Unified orchestrator, summaries, morning schedule, controlled setup rollout, review/release.

No phase may claim completion while its test, review, migration, rollout, or live readback gate is outstanding.

## 14. Definition of done

The program is complete when:

1. Every completed U.S. session is evaluated once with an immutable run identity.
2. Data readiness distinguishes complete, partial, stale, and unavailable states.
3. The production universe is versioned, U.S.-eligible, liquid, source-backed, and broader than 34 after shadow acceptance.
4. Every eligible ticker/setup has a pass/fail gate record and reason facts.
5. The approved breakout is unchanged and parity-tested.
6. Pullback and volatility-contraction setups have governed research/backtest paths and separate status.
7. Breadth and event inputs are point-in-time/provenance-safe.
8. Exact read-only chains yield long call, call debit spread, or no option—never equity fallback.
9. One allocator enforces 5% paper risk, global max-three, heat, duplication, sector, and correlation constraints.
10. Underlying and option outcomes are separately logged and reviewed.
11. An incomplete pipeline never emits a false no-trade.
12. The daily schedule works in free T+1 mode before the next session and can switch to paid current-day only after entitlement verification.
13. All tests run against an isolated database, all reviews approve the final staged snapshot, the branch is pushed, and live paper-only readback proves zero broker orders.
