# Wolfy Mid/Small-Cap Multi-Strategy Pivot Implementation Plan

> **For Hermes:** Use the subagent-driven-development skill to implement this plan task-by-task. Every behavior change follows RED-GREEN-REFACTOR, then independent spec-compliance and code-quality review. This document is a plan only; do not mutate production data or enable production schedules while implementing it.

**Goal:** Deliver a paper-only Wolfy recommendation pipeline that ranks eligible U.S. mid/small-cap common stocks across multiple deterministic setups, prefers a fresh exact defined-risk option when safe, falls back to the underlying stock otherwise, manages up to 20 concurrent 5%-risk recommendations with no more than five per sector, and measures outcomes including accepted account-ruin risk.

**Architecture:** Reuse the existing dedicated `wolfy_test` harness, immutable daily-run ledger, EOD readiness resolver, approved close-confirmed breakout, and options selector instead of recreating them. Add a point-in-time stock-only universe and common setup-candidate contract, route every setup through one global rank/allocator and one serialized writer, then attach an exact-chain instrument decision and separate underlying/option outcome ledgers. SPY, IWM, and MDY are context-only benchmarks; because ETF recommendations conflict with the approved stock-only universe, replace the proposed ETF-rotation sleeve with weekly mid/small-cap industry/sector relative-strength allocation over eligible common stocks.

**Tech Stack:** Python 3.12, PostgreSQL 16, psycopg 3, pytest, existing Massive adjusted EOD pipeline, existing Cboe delayed read-only option adapter (optional read-only broker context only), Hermes cron, concise Discord delivery.

---

## 1. Supersession and reconciliation with the accepted plan

This plan is the approved policy pivot and must be implemented from branch `wolfy/mid-small-strategy-pivot` at or after `5c4b249`. It reconciles rather than duplicates the accepted 26-task plan at `.hermes/plans/2026-08-23_191625-wolfy-daily-multi-setup-evaluator.md`:

- **Reuse as completed foundations:** `wolfy/test_db.py`, `wolfy/conftest.py`, `wolfy/eod_readiness.py`, `wolfy/daily_evaluation_ledger.py`, their tests, and the canonical run/manifest/gate schema in `wolfy/postgres_init.sql`.
- **Preserve and adapt:** approved close-confirmed breakout generation in `wolfy/eod_signals.py`, option selection in `wolfy/options_structure_selector.py`, option evaluation in `wolfy/experimental_options_pipeline.py`, outcome review in `wolfy/recommendation_outcome_review.py`, orchestration in `wolfy/orchestration_runner.py`, and concise delivery in `wolfy/recommendation_engine_daily_summary.py`.
- **Supersede old policy:** stock recommendations are U.S. common stocks only; eligible market cap is $200M-$15B, close is at least $3, and trailing 20-session average dollar volume is at least $5M. ETFs (including SPY/IWM/MDY) are never recommendation candidates. The global cap is up to 20 concurrent recommendations/open paper positions, 5% defined paper risk each, 100% aggregate paper risk, and at most five positions in one sector. Account ruin is accepted for this paper experiment and must be measured rather than hidden by an unapproved lower heat cap.
- **Supersede old option behavior:** a fresh exact safe option is preferred; when no safe option exists, publish the already-qualified underlying stock as an explicit fallback. Underlying and option outcomes remain separate.
- **Resolve ETF-rotation incompatibility:** do not recommend weekly ETFs. Use SPY/IWM/MDY only for benchmark/regime context and implement weekly relative-strength allocation among eligible stocks grouped by point-in-time U.S. industry/sector.
- **Do not revive deferred scope:** PEAD, short strategies, live trading, broker writes, paid-data purchases, and automatic strategy approval remain out of scope.

Before each implementation task, inspect current code because commits `14ea5aa` and `5c4b249` partially implement aggressive options v2. Extend or refactor those paths; do not add a parallel recommendation engine.

## 2. Non-negotiable contracts

1. **Paper only:** no live orders, cancellations, exercise, money movement, or broker writes. Every emitted recommendation/trade/evaluation records `paper_only=true`, `no_live_execution=true`, and `broker_order_submitted=false`.
2. **Production isolation:** all RED/GREEN tests and migration rehearsals run against exact database `wolfy_test`. No production DML, migration, cron edit, or external delivery occurs before Task 23's release gate.
3. **Point-in-time:** universe identity, market cap, sector/industry, security status, price/liquidity, benchmark context, and option quotes must have `available_at <= decision_at`. Unknown or conflicting identity fails closed.
4. **Recommendation universe:** only source-verified U.S. common stocks with market cap in inclusive range `[200_000_000, 15_000_000_000]`, signal-date close `>= 3`, and mean of `close * volume` across exactly the latest 20 sessions through the signal date `>= 5_000_000`.
5. **Absolute exclusions:** foreign issuers/listings and ADRs, OTC, ETFs/ETPs (especially leveraged/inverse/single-stock products), preferreds, warrants, rights, units, funds, ambiguous identities, inactive/delisted names, user denylist entries, manipulation-risk names, and foreign/government-interference-risk names.
6. **Benchmarks only:** SPY, IWM, and MDY may be read for market regime and relative-strength denominators but cannot enter setup candidates, rankings, recommendations, paper trades, or outcomes.
7. **Strategies:** preserve approved close-confirmed breakout unchanged; add trend pullback/reclaim, volatility-contraction breakout, and weekly industry/sector RS allocation as separately versioned research families.
8. **One allocator:** globally rank all eligible candidate/setup rows, deduplicate ticker, enforce 20 total concurrent/recommended positions, 5% defined risk per position, 100% aggregate risk, and maximum five per sector. Fewer or zero is valid.
9. **Instrument expression:** for each selected underlying, choose exactly one of `long_call`, `call_debit_spread`, or `underlying_stock_fallback`. An option requires a fresh exact read-only chain and a deterministic bounded-loss selection; no safe option means stock fallback, not candidate loss.
10. **Outcome separation:** setup/underlying outcomes judge strategy quality; option outcomes judge option expression quality. Stock fallback outcomes are underlying-only. Option P&L cannot rewrite an underlying strategy gate.
11. **Accepted ruin risk:** do not add an unapproved lower heat cap. Backtests and paper reports must show drawdown, risk utilization, ruin incidence/probability estimate, time to ruin, loss streaks, and terminal equity under the approved 5% x 20 policy.
12. **Governance:** new strategies begin `research_only`; backtests may promote only to `candidate`; explicit user approval is required before they can produce paper recommendations. The already approved breakout keeps its immutable approval metadata and parity gate.

## 3. Target flow and core records

```text
EOD readiness + immutable DailyEvaluationRun(decision_at distinct from evaluated_at)
  -> point-in-time U.S. common-stock universe snapshot
  -> breakout + pullback + VCP + weekly industry/sector-RS evaluations
  -> common SetupCandidate rows and gate/near-miss ledger
  -> global ticker dedupe/rank + 20-slot/100%-risk/5-per-sector allocator
  -> exact fresh read-only chain snapshot for selected finalists only
       -> long_call | call_debit_spread | underlying_stock_fallback
  -> one serialized paper recommendation writer
  -> paper ledger
  -> separate underlying and option outcome reviewers
  -> concise recommendation / clean no-trade / pipeline-incomplete delivery
```

Required immutable identities:

```python
UniverseSnapshot(snapshot_id, signal_dt, decision_at, policy_version, source_fingerprint)
SetupCandidate(run_id, ticker, strategy_id, strategy_version, sector, score, entry, stop, target, facts_hash)
OptionChainSnapshot(snapshot_id, ticker, provider, source_url, fetched_at, market_at, available_at, payload_sha256)
InstrumentDecision(candidate_id, ticker, decision_at, chain_snapshot_id, selector_version, expression, max_loss)
AllocationDecision(run_id, ticker, global_rank, sector_rank, risk_fraction, selected, reason)
```

`decision_at` is supplied by the orchestration run and never derived from evaluation time, insert time, chain fetch time, or wall-clock `now()` inside an evaluator. `evaluated_at`/`created_at` are audit timestamps only.

## 4. Implementation tasks (24 total)

### Task 1: Freeze the pivot contract and baseline the existing foundations

**Objective:** Prove which accepted-plan components already exist and prevent duplicate implementations.

**Files:**
- Create: `wolfy/test_mid_small_pivot_contract.py`
- Modify only if a contract constant has no canonical home: `wolfy/orchestration_config.py`

**RED:** Add an import-level contract test asserting the policy version, market-cap/price/ADV boundaries, benchmark-only set `{SPY,IWM,MDY}`, max 20, 5% risk, 100% aggregate risk, max five per sector, and paper/no-live flags. Assert `test_db`, readiness, and daily-ledger APIs are reused.

**Run:**
```bash
cd wolfy && python3 -m pytest test_mid_small_pivot_contract.py -q
```
Expected RED: missing canonical pivot policy.

**GREEN:** Add one frozen policy dataclass/constants module surface; do not build behavior yet. Record a baseline test list and current production read-only count query in the implementation log, but perform no production write.

**Verify:** Focused test passes; `git diff --name-only` shows only policy/test files for this task.

**Commit:** `test(wolfy): freeze mid small pivot contract`

### Task 2: Close aggressive-options v2 parsing and clock review blockers

**Objective:** Make exact-chain input fail closed before reusing it in the pivot.

**Files:**
- Modify: `wolfy/options_structure_selector.py`
- Modify: `wolfy/cboe_delayed_options.py`
- Modify: `wolfy/run_experimental_options_forward_test.py`
- Modify: `wolfy/test_options_structure_selector.py`
- Modify: `wolfy/test_cboe_delayed_options.py`
- Modify: `wolfy/test_run_experimental_options_forward_test.py`

**RED:** Parameterize malformed numeric values (`bool`, null where required, NaN, infinity, strings with whitespace/exponents where canonical integers are required), malformed chain containers, negative OI/volume, and OI/volume greater than a documented bound (use signed 32-bit maximum unless provider contract proves a lower bound). Assert naive `decision_at`, `fetched_at`, `quote_at`, and snapshot timestamps are rejected, never assumed UTC. Assert `decision_at` remains unchanged when `evaluated_at` changes.

**GREEN:** Replace permissive conversions/defaults with shared strict finite-decimal, canonical bounded-nonnegative-integer, aware-datetime, mapping, and sequence validators. Keep `decision_at` explicit and independent.

**Run/verify:**
```bash
cd wolfy
python3 -m pytest test_options_structure_selector.py test_cboe_delayed_options.py test_run_experimental_options_forward_test.py -q
```
Expected GREEN: all focused tests pass and malformed values return canonical rejection reasons or raise at the input boundary without writes.

**Commit:** `fix(wolfy): fail closed on malformed option inputs`

### Task 3: Bind options evaluations to ticker and durable snapshot provenance

**Objective:** Prevent a valid-looking evaluation from being replayed against another ticker or unverifiable chain.

**Files:**
- Create: `wolfy/migrations/20260917_option_snapshot_provenance.sql`
- Modify: `wolfy/postgres_init.sql`
- Modify: `wolfy/options_research_ledger.py`
- Modify: `wolfy/experimental_options_pipeline.py`
- Modify: `wolfy/eod_signals.py`
- Modify: `wolfy/test_options_research_ledger.py`
- Modify: `wolfy/test_experimental_options_pipeline.py`
- Modify: `wolfy/test_experimental_options_recommendations.py`

**RED:** Test that recommendation writing rejects evaluation ticker mismatch, OCC underlying mismatch, missing snapshot ID/hash/source/available time, changed chain payload under the same ID, recommendation/evaluation strategy mismatch, and snapshot availability after `decision_at`.

**GREEN:** Add append-only `option_chain_snapshots` with durable payload hash or immutable object reference, canonical source metadata, ticker, fetched/market/available timestamps, and unique snapshot identity. Add an FK from `option_structure_evaluations` to the snapshot, include candidate/run identity, and bind recommendation notes/columns to evaluation ID and snapshot ID. Recompute the selected structure from the stored snapshot before writing.

**Migration rule:** validate populated rows first; backfill only when ticker/source/time/hash are defensible. Otherwise abort with an actionable exception—never synthesize provenance.

**Run:**
```bash
cd wolfy && python3 -m pytest test_options_research_ledger.py test_experimental_options_pipeline.py test_experimental_options_recommendations.py -q
```

**Commit:** `feat(wolfy): bind option decisions to durable snapshots`

### Task 4: Replace runtime unique-index creation with an explicit safe migration

**Objective:** Make recommendation idempotency a reviewed schema migration rather than runtime DDL.

**Files:**
- Create: `wolfy/migrations/20260917_recommendation_uniqueness.sql`
- Modify: `wolfy/postgres_init.sql`
- Modify: `wolfy/eod_signals.py`
- Create: `wolfy/test_recommendation_uniqueness_migration.py`
- Modify: `wolfy/test_eod_signals.py`

**RED:** On `wolfy_test`, cover clean bootstrap, populated valid schema, duplicate legacy rows, rerun, concurrent migration attempts, and mixed recommendation statuses. Require duplicate preflight to report keys and abort without deleting/merging rows.

**GREEN:** Move `uq_experimental_paper_recommendation_signal` and the canonical all-instrument recommendation identity into an explicit transactionally locked migration. Remove `CREATE UNIQUE INDEX` from `ensure_signal_schema`; keep insert conflict handling aligned with the migrated key.

**Run:**
```bash
cd wolfy && python3 -m pytest test_recommendation_uniqueness_migration.py test_eod_signals.py -q
```

**Commit:** `fix(wolfy): migrate recommendation uniqueness explicitly`

### Task 5: Serialize every recommendation writer under one global cap lock

**Objective:** Ensure approved, experimental, option, and stock-fallback writers cannot race past the global cap.

**Files:**
- Create: `wolfy/recommendation_writer.py`
- Create: `wolfy/test_recommendation_writer.py`
- Modify: `wolfy/eod_signals.py`
- Modify: `wolfy/orchestration_runner.py`
- Modify: `wolfy/test_experimental_options_recommendations.py`
- Modify: `wolfy/test_eod_signals.py`
- Modify: `wolfy/test_orchestration_runner.py`

**RED:** Use two real `wolfy_test` connections and barriers to race approved and experimental writers for the same run/date. Assert one shared transaction advisory lock, one recount after lock acquisition, no duplicate ticker, no more than available slots, max 20 open/recommended globally, max five per sector, and aggregate defined risk no greater than 100%.

**GREEN:** Centralize locking, existing-position accounting, remaining-slot calculation, and insert in `recommendation_writer.py`. Every writer must call it; no writer owns a private cap. Dry-run returns a deterministic preview without acquiring a write lock or mutating rows.

**Run:**
```bash
cd wolfy && python3 -m pytest test_recommendation_writer.py test_experimental_options_recommendations.py test_eod_signals.py test_orchestration_runner.py -q
```

**Commit:** `fix(wolfy): share global recommendation cap lock`

### Task 6: Add point-in-time security identity and risk observations

**Objective:** Provide source-backed identity for stock-only eligibility and exclusions.

**Files:**
- Create: `wolfy/migrations/20260917_security_master.sql`
- Modify: `wolfy/postgres_init.sql`
- Create: `wolfy/security_master.py`
- Create: `wolfy/test_security_master.py`
- Reuse, do not import policy from: `wolfy/suspicious_activity.py`

**RED:** Cover U.S. common stock, ADR, foreign issuer/listing, OTC, ETF/ETP, leveraged/inverse/single-stock ETF, preferred, unit, right, warrant, inactive/delisted, unknown/conflicting identity, manipulation veto, government-risk veto, denylist effective dates, stale source, and `available_at > decision_at`.

**GREEN:** Add append-only effective-dated source observations and denylist/risk decisions with canonical reason codes. Exact provider type/locale/market/exchange/currency fields—not ticker/name heuristics—decide identity. A risk observation can veto but cannot make unknown identity eligible.

**Run:**
```bash
cd wolfy && python3 -m pytest test_security_master.py -q
```

**Commit:** `feat(wolfy): add point in time stock identity gate`

### Task 7: Build the versioned mid/small-cap universe snapshot

**Objective:** Materialize the exact eligible recommendation universe before signal evaluation.

**Files:**
- Create: `wolfy/migrations/20260917_recommendation_universe.sql`
- Modify: `wolfy/postgres_init.sql`
- Create: `wolfy/recommendation_universe.py`
- Create: `wolfy/test_recommendation_universe.py`
- Modify: `wolfy/eod_signals.py`

**RED:** Test inclusive $200M/$15B, $3, and $5M boundaries; just-outside values; market cap available after decision; exactly 19 versus 20 sessions; adjusted `close * volume`; missing/duplicate bars; benchmark exclusion; all security/risk exclusions; deterministic members, reasons, count, and fingerprint.

**GREEN:** Persist immutable snapshot header and one included/excluded decision per symbol. Market cap must be point-in-time and source-backed. Compute ADV from exactly the latest 20 sessions ending on `signal_dt`; no one-day proxy and no stale carry-forward. Replace `recommendation_universe_tickers()` internals with a snapshot-backed adapter while retaining explicit ticker replay only when every ticker independently passes the same policy.

**Run:**
```bash
cd wolfy && python3 -m pytest test_recommendation_universe.py test_eod_signals.py -q
```

**Commit:** `feat(wolfy): snapshot mid small stock universe`

### Task 8: Extend readiness for universe and benchmark completeness

**Objective:** Distinguish a trustworthy empty run from incomplete stock/benchmark data.

**Files:**
- Modify: `wolfy/eod_readiness.py`
- Modify: `wolfy/test_eod_readiness.py`
- Modify: `wolfy/orchestration_runner.py`
- Modify: `wolfy/test_orchestration_runner.py`

**RED:** Require complete current rows for every accepted universe member and SPY/IWM/MDY, a valid universe snapshot, point-in-time market caps/identity, and exact feature dates. Cover missing benchmark, partial member data, empty-but-valid universe, stale snapshot, replay without historical snapshot, and data becoming available after decision.

**GREEN:** Extend the typed readiness payload with snapshot ID/policy/fingerprint, benchmark coverage, member coverage, and canonical incomplete reasons. Do not weaken the existing pinned NYSE session logic.

**Run:**
```bash
cd wolfy && python3 -m pytest test_eod_readiness.py test_orchestration_runner.py -q
```

**Commit:** `feat(wolfy): gate pivot on complete universe readiness`

### Task 9: Define one setup-evaluation and candidate contract

**Objective:** Let heterogeneous strategies feed one auditable allocator without strategy-specific writer paths.

**Files:**
- Create: `wolfy/setup_evaluators.py`
- Create: `wolfy/test_setup_evaluators.py`
- Modify: `wolfy/daily_evaluation_ledger.py`
- Modify: `wolfy/test_daily_evaluation_ledger.py`
- Modify: `wolfy/postgres_init.sql`

**RED:** Validate finite numeric fields, positive entry, stop below entry, target above entry, canonical strategy/version, ticker/snapshot/run binding, sector presence, facts hash, deterministic score components, and exactly one terminal gate evaluation per run/ticker/strategy. Malformed JSON containers or numerics fail closed.

**GREEN:** Add immutable `SetupEvaluation` and `SetupCandidate` types plus persisted candidate rows linked to daily run, universe snapshot, strategy, and gate evaluation. Extend canonical reason codes via an explicit versioned migration rather than changing version 1 in place.

**Run:**
```bash
cd wolfy && python3 -m pytest test_setup_evaluators.py test_daily_evaluation_ledger.py -q
```

**Commit:** `feat(wolfy): add common setup candidate contract`

### Task 10: Preserve the approved close-confirmed breakout with golden parity

**Objective:** Move the approved strategy onto the common contract with zero rule drift.

**Files:**
- Modify: `wolfy/setup_evaluators.py`
- Modify: `wolfy/eod_signals.py`
- Create: `wolfy/test_breakout_parity.py`
- Modify: `wolfy/test_eod_signals.py`

**RED:** Compare legacy and adapter pass/fail, entry, prior-five-session breakout/invalidation, RS versus SPY, volume ratio, market gate, target R, max hold, and raw facts across known fixtures and representative historical fixture dates. Verify IWM/MDY do not alter approved rules.

**GREEN:** Extract an adapter around the current approved logic; do not tune thresholds or authorization metadata. Emit gate facts/candidate only after universe eligibility.

**Run:**
```bash
cd wolfy && python3 -m pytest test_breakout_parity.py test_eod_signals.py -q
```
Expected: zero signal drift for the parity fixture.

**Commit:** `refactor(wolfy): adapt approved breakout without drift`

### Task 11: Deliver the minimally useful underlying-only vertical slice

**Objective:** Produce ranked paper stock recommendations quickly before chain integration or new sleeves.

**Files:**
- Create: `wolfy/portfolio_allocator.py`
- Create: `wolfy/test_portfolio_allocator.py`
- Create: `wolfy/daily_multi_strategy.py`
- Create: `wolfy/test_daily_multi_strategy.py`
- Modify: `wolfy/orchestration_runner.py`
- Modify: `wolfy/recommendation_writer.py`

**RED:** End-to-end test: ready snapshot -> approved breakout candidates -> global rank -> ticker dedupe -> remaining 20 slots -> five-per-sector -> 5% each -> aggregate <=100% -> `underlying_stock_fallback` recommendation -> idempotent rerun. Cover zero candidates, 20 existing positions, four existing sector positions, ties, malformed candidate, and pipeline incomplete.

**GREEN:** Implement deterministic score normalization and one allocator. Until exact-chain Tasks 12–14 land, mark instrument reason `option_engine_not_release_ready` and use stock fallback only in isolated shadow/test mode; do not enable production publication.

**Run:**
```bash
cd wolfy && python3 -m pytest test_portfolio_allocator.py test_daily_multi_strategy.py test_recommendation_writer.py -q
```

**Commit:** `feat(wolfy): add underlying pivot vertical slice`

### Task 12: Normalize fresh exact read-only chain acquisition

**Objective:** Fetch option chains only for allocated finalists and persist exact provenance.

**Files:**
- Create: `wolfy/option_chain_provider.py`
- Create: `wolfy/test_option_chain_provider.py`
- Modify: `wolfy/cboe_delayed_options.py`
- Modify: `wolfy/experimental_options_pipeline.py`
- Modify: `wolfy/run_experimental_options_forward_test.py`

**RED:** Cover exact ticker, source priority, provider outage, malformed payload/container, quote timestamp after decision, naive timestamp, stale market date/quote age, partial chains, duplicate contracts, OCC mismatch, negative/bounded OI/volume, payload hash stability, and no broker-write methods.

**GREEN:** Return/persist a typed `OptionChainSnapshot`. Cboe delayed remains the default read-only source. Any broker adapter is optional context and must expose an explicit read-only allowlist; place/cancel/replace/exercise/money-movement operations must be absent.

**Run:**
```bash
cd wolfy && python3 -m pytest test_option_chain_provider.py test_cboe_delayed_options.py test_experimental_options_pipeline.py test_run_experimental_options_forward_test.py -q
```

**Commit:** `feat(wolfy): normalize exact read only option chains`

### Task 13: Produce option-preferred or stock-fallback instrument decisions

**Objective:** Make instrument choice deterministic without discarding a valid underlying setup.

**Files:**
- Modify: `wolfy/options_structure_selector.py`
- Create: `wolfy/instrument_decision.py`
- Create: `wolfy/test_instrument_decision.py`
- Modify: `wolfy/test_options_structure_selector.py`

**RED:** Cover safe long call, safe call debit spread, no chain, stale chain, unaffordable one-contract max loss, wide spread, insufficient liquidity, malformed chain, target below break-even, ticker/provenance mismatch, deterministic tie, and fallback reason. Assert fallback preserves underlying risk sizing and never fabricates an option.

**GREEN:** Prefer the highest-ranked safe exact option under its 5% maximum-loss budget. Otherwise return `underlying_stock_fallback` with the option rejection reasons and 5% stop-defined stock sizing. Keep `decision_at` from the run, not evaluation time.

**Run:**
```bash
cd wolfy && python3 -m pytest test_instrument_decision.py test_options_structure_selector.py -q
```

**Commit:** `feat(wolfy): prefer exact options with stock fallback`

### Task 14: Complete the recommendation and paper-ledger vertical slice

**Objective:** Persist globally allocated recommendations with exact instrument decisions and no live action.

**Files:**
- Modify: `wolfy/recommendation_writer.py`
- Modify: `wolfy/eod_signals.py`
- Modify: `wolfy/orchestration_runner.py`
- Modify: `wolfy/test_recommendation_writer.py`
- Modify: `wolfy/test_eod_signals.py`
- Modify: `wolfy/test_orchestration_runner.py`

**RED:** Test option and stock-fallback inserts, exact evaluation/snapshot binding, 5% maximum option loss or stop-defined stock risk, 20/100%/sector caps under concurrency, paper-only flags, approval metadata, idempotency, and `broker_orders_created=0`. Reject malformed notes/containers/numerics.

**GREEN:** Route approved candidates through the shared writer and paper logger. Store instrument type, exact legs when present, max loss/risk amount, candidate/allocation IDs, decision time, snapshot provenance, and fallback reason. Remove misleading `equity_fallback_plus_option_spread_advisory` from new rows while retaining read compatibility for legacy rows.

**Run:**
```bash
cd wolfy && python3 -m pytest test_recommendation_writer.py test_eod_signals.py test_orchestration_runner.py -q
```

**Commit:** `feat(wolfy): persist pivot instrument recommendations`

### Task 15: Separate underlying, option, and fallback outcomes

**Objective:** Measure setup alpha independently from expression quality.

**Files:**
- Create: `wolfy/migrations/20260917_instrument_outcomes.sql`
- Modify: `wolfy/postgres_init.sql`
- Modify: `wolfy/recommendation_outcome_review.py`
- Create: `wolfy/option_outcome_review.py`
- Create: `wolfy/test_option_outcome_review.py`
- Modify: `wolfy/test_recommendation_outcome_review.py`

**RED:** Cover underlying target/stop/time exit, next-session entry/gap handling, same-bar stop-first, option quote/mark provenance, long-call/spread expiration and max loss, stale/missing marks, stock fallback with no option row, idempotent closure, and inability of option P&L to mutate underlying governance.

**GREEN:** Keep/create one underlying outcome for every recommendation and create an option outcome only for exact option expressions, linked to evaluation and snapshot. Stock fallback uses the underlying outcome and explicit `option_outcome_not_applicable`.

**Run:**
```bash
cd wolfy && python3 -m pytest test_recommendation_outcome_review.py test_option_outcome_review.py -q
```

**Commit:** `feat(wolfy): separate setup and option outcomes`

### Task 16: Add concise trustworthy delivery

**Objective:** Report actionable recommendations without confusing incomplete pipelines with no trade.

**Files:**
- Modify: `wolfy/recommendation_engine_daily_summary.py`
- Modify: `wolfy/test_recommendation_engine_daily_summary.py`
- Modify: `wolfy/wolfy_report_context.py`

**RED:** Cover `pipeline_incomplete`, clean `NO TRADE`, allocation blocked, option selected, stock fallback, mixed list, and cap-full states. Require signal date, strategy, rank, sector, entry/stop/target, risk/max loss, exact option legs or fallback reason, and paper/no-live wording.

**GREEN:** Emit concise output only for actionable recommendations, meaningful progression, or exceptional blockers. Routine health stays local. Never label partial data as no setup.

**Run:**
```bash
cd wolfy && python3 -m pytest test_recommendation_engine_daily_summary.py -q
```

**Commit:** `feat(wolfy): summarize pivot recommendations concisely`

### Task 17: Add trend pullback/reclaim as research-only

**Objective:** Add the first new orthogonal setup after the vertical slice works.

**Files:**
- Modify: `wolfy/setup_evaluators.py`
- Modify: `wolfy/eod_signals.py` (strategy seed/adapter only)
- Create: `wolfy/test_trend_pullback_strategy.py`

**RED:** Freeze and test 50/200 trend stack, rising 50DMA, SPY/IWM/MDY benchmark context, 2–7-session pullback, 20DMA/ATR proximity, no 50DMA breach, contracting pullback volume, predeclared reclaim trigger variants, stop below swing low, maximum stop risk, and event/risk veto.

**GREEN:** Seed `mid_small_trend_pullback_reclaim_v1` as `research_only`; emit evaluations/candidates to shadow only. No backtest result auto-approves it.

**Run:**
```bash
cd wolfy && python3 -m pytest test_trend_pullback_strategy.py test_setup_evaluators.py -q
```

**Commit:** `feat(wolfy): add research trend pullback sleeve`

### Task 18: Add volatility-contraction breakout as research-only

**Objective:** Reuse existing volatility features for a separately governed setup.

**Files:**
- Modify: `wolfy/setup_evaluators.py`
- Modify: `wolfy/eod_signals.py` (strategy seed/adapter only)
- Modify: `wolfy/test_options_volatility_strategy.py`
- Modify: `wolfy/test_aggressive_options_v2.py`

**RED:** Test contraction ratio, range expansion, close location, volume percentile, trend/RS confirmation, point-in-time context, missing/stale feature failure, stop/target, and separation of `underlying_setup_passed` from instrument selection. Retain aggressive-v2 review regressions.

**GREEN:** Seed `mid_small_volatility_contraction_breakout_v1` as `research_only`; produce underlying candidates without requiring a chain. Chain availability affects expression only.

**Run:**
```bash
cd wolfy && python3 -m pytest test_options_volatility_strategy.py test_aggressive_options_v2.py test_setup_evaluators.py -q
```

**Commit:** `feat(wolfy): add research volatility contraction sleeve`

### Task 19: Replace ETF rotation with weekly industry/sector stock allocation

**Objective:** Preserve the weekly relative-strength idea without violating the stock-only universe.

**Files:**
- Create: `wolfy/weekly_relative_strength.py`
- Create: `wolfy/test_weekly_relative_strength.py`
- Modify: `wolfy/setup_evaluators.py`
- Modify: `wolfy/eod_signals.py` (strategy seed/adapter only)

**RED:** Assert SPY/IWM/MDY and all ETFs can be benchmark/context rows but never candidates. Cover weekly decision schedule, point-in-time sector/industry membership, missing sector failure, group RS ranking, stock ranking within leading groups, no lookahead, rebalance idempotency, and max-five-per-sector handoff to allocator.

**GREEN:** Seed `mid_small_weekly_industry_rs_allocation_v1` as `research_only`. Compute group strength from eligible constituent stocks with SPY/IWM/MDY context; emit eligible common-stock candidates only. The global allocator—not this sleeve—owns final count and concentration.

**Run:**
```bash
cd wolfy && python3 -m pytest test_weekly_relative_strength.py test_setup_evaluators.py -q
```

**Commit:** `feat(wolfy): add weekly stock relative strength sleeve`

### Task 20: Add setup-native chronological backtests and governance

**Objective:** Validate each strategy without contaminating the preserved approved gate.

**Files:**
- Modify: `wolfy/eod_backtest.py`
- Modify: `wolfy/eod_monitoring.py`
- Create: `wolfy/test_multi_strategy_backtest.py`
- Modify: `wolfy/test_eod_backtest.py`
- Modify: `wolfy/test_eod_monitoring.py`

**RED:** Cover anchored/rolling chronological splits, purged hold boundaries, untouched holdout, next-session-open and EOD-reference entries, gaps, stop-first same bar, costs/slippage, delisting/missing bars, available-at joins, attempted-parameter logging, concentration, overlap, and immutable approval metadata.

**GREEN:** Add versioned backtest modes for breakout parity, pullback, VCP, and weekly industry RS. Report sample counts, hit/stop rates, expectancy in R, drawdown, MFE/MAE, turnover, holding period, sector/regime concentration, date-clustered confidence intervals, sensitivity, and overlap. New families may become `candidate` only after their governed gate; explicit user approval remains mandatory.

**Run:**
```bash
cd wolfy && python3 -m pytest test_multi_strategy_backtest.py test_eod_backtest.py test_eod_monitoring.py -q
```

**Commit:** `feat(wolfy): govern multi strategy backtests`

### Task 21: Backtest portfolio allocation and measure accepted ruin risk

**Objective:** Quantify the consequences of 20 concurrent positions at 5% defined risk each.

**Files:**
- Create: `wolfy/portfolio_backtest.py`
- Create: `wolfy/test_portfolio_backtest.py`
- Modify: `wolfy/eod_backtest.py`

**RED:** Cover simultaneous candidates, global ranking, ticker dedupe, sector cap, open-position carry, exact 5% sizing from current paper equity, 100% aggregate risk, correlated same-day losses, equity <= 0 ruin, no resurrection after ruin, deterministic bootstrap/scenario seeds, and option versus stock expression costs without pooling outcome labels.

**GREEN:** Replay the allocator chronologically and report max drawdown, terminal equity, risk utilization, worst day/week, longest loss streak, ruin occurrence, time/date to ruin, historical ruin frequency, block/bootstrap confidence interval for ruin probability, and results by strategy/sector/regime. Label model limits; accepted ruin is measured, not declared safe.

**Run:**
```bash
cd wolfy && python3 -m pytest test_portfolio_backtest.py test_eod_backtest.py -q
```

**Commit:** `feat(wolfy): measure portfolio ruin risk`

### Task 22: Build the idempotent full orchestrator in shadow mode

**Objective:** Join readiness, all evaluators, allocator, chain decisions, writer, outcomes, and summary behind one state machine.

**Files:**
- Modify: `wolfy/daily_multi_strategy.py`
- Modify: `wolfy/orchestration_runner.py`
- Create: `scripts/wolfy_mid_small_daily.py`
- Modify: `wolfy/test_daily_multi_strategy.py`
- Modify: `wolfy/test_orchestration_runner.py`

**RED:** Test complete run, missing universe/benchmark, no candidates, all allocation-blocked, chain outage with stock fallback, malformed chain, stage crash/retry, same fingerprint rerun, conflicting fingerprint, research-only leakage prevention, 20-position capacity, zero broker actions, and no external delivery in shadow.

**GREEN:** Implement immutable stages: readiness -> universe -> features/context -> setup evaluations -> candidate persistence -> allocation -> finalist chains -> instrument decisions -> serialized write (disabled in shadow) -> outcomes -> summary. Support `--dry-run`, `--shadow`, `--signal-dt`, `--strategy`, and bounded ticker replay. Published status requires read-back of every required stage.

**Run:**
```bash
cd wolfy && python3 -m pytest test_daily_multi_strategy.py test_orchestration_runner.py -q
```

**Commit:** `feat(wolfy): orchestrate pivot in shadow mode`

### Task 23: Rehearse migrations and run the staged shadow release

**Objective:** Prove production safety and behavior before any production mutation.

**Files:**
- Create: `wolfy/shadow_pivot_report.py`
- Create: `wolfy/test_shadow_pivot_report.py`
- Modify migration files from Tasks 3, 4, 6, 7, and 15 only when rehearsal reveals a defect.

**Steps:**
1. Capture read-only production baselines for strategies, recommendations, paper trades, outcomes, approved metadata, and schema versions.
2. Provision a fresh `wolfy_test`, apply the full canonical schema and every new migration twice, then test upgrade from populated pre-pivot fixtures.
3. Run focused suites, then the full suite serially:
   ```bash
   cd wolfy
   python3 -m pytest test_mid_small_pivot_contract.py test_security_master.py test_recommendation_universe.py test_setup_evaluators.py test_portfolio_allocator.py test_instrument_decision.py test_daily_multi_strategy.py -q
   python3 -m pytest -q
   ```
4. Run at least five complete-session read-only/shadow replays covering ordinary, no-signal, chain-unavailable, sector-concentrated, and near-cap cases.
5. Compare breakout parity, universe exclusions, ranks, options/fallbacks, runtime, and deterministic reruns. Shadow must create no production recommendations/trades/outcomes.
6. Request independent spec-compliance review, then code-quality/security review of the exact staged snapshot; rerun reviews if it changes.
7. Secret-scan staged changes and verify production baselines are unchanged.

**Release gates:** 100% SPY/IWM/MDY freshness; complete accepted-universe data; zero ineligible symbols; zero breakout drift; deterministic rerun; no malformed input accepted; global lock concurrency passes; <=20 positions; <=5/sector; exactly 5% per selected position; <=100% aggregate risk; exact-chain provenance or explicit stock fallback; separate outcomes; zero broker-write capability; migration rerun/upgrade passes; full suite passes; independent reviews approve.

**Commit:** `test(wolfy): validate pivot shadow release`

### Task 24: Gate production activation, canary, and rollback

**Objective:** Activate only the approved breakout vertical slice first and retain a one-command rollback.

**Files:**
- Modify after Task 23 approval only: `scripts/wolfy_mid_small_daily.py`
- Modify through Hermes cron management after Task 23 approval only: `cron/jobs.json`
- Modify: `wolfy/test_orchestration_runner.py`
- Modify: `wolfy/test_recommendation_engine_daily_summary.py`

**RED:** Assert default production invocation remains disabled before an explicit release flag/config version; research-only strategies cannot publish; rollback restores the prior publisher/universe without deleting rows; cron has one publisher; canary remains paper-only.

**GREEN/release order:**
1. Apply reviewed migrations to production in one bounded maintenance step; read back constraints/indexes and stop on any preflight failure.
2. Enable only the unchanged approved breakout over the accepted stock universe. New sleeves remain shadow/research-only.
3. Run one scoped paper-only canary, then an idempotent rerun. Verify recommendation, allocation, risk, instrument provenance/fallback, paper flags, outcomes linkage, and `broker_orders_created=0`.
4. Read back global count/sector/risk invariants and production baseline deltas.
5. Enable one scheduled publisher only after canary success. Keep routine output local.
6. Roll back by disabling the pivot publisher/config and restoring the previous publisher; never delete audit/recommendation rows as rollback.
7. Promote each new sleeve only after Task 20/21 evidence, forward shadow evidence, independent review, and explicit user approval.

**Run:**
```bash
cd wolfy && python3 -m pytest test_orchestration_runner.py test_recommendation_engine_daily_summary.py -q
python3 -m pytest -q
```

**Commit:** `ops(wolfy): gate pivot paper release`

## 5. TDD and review protocol for every task

For each task that changes behavior:

1. Write the smallest focused failing test and run its exact node ID; capture the expected failure.
2. Implement only enough production code to pass it.
3. Run the node, its file, adjacent files named in the task, then the listed task command.
4. Refactor only while green; rerun focused tests.
5. For database work, apply migrations only to `wolfy_test`, verify `current_database()='wolfy_test'`, test populated upgrade and rerun, and confirm production read-only baselines are unchanged.
6. Request independent spec review and code-quality/security review for concurrency, schema, allocator, provenance, and release tasks.
7. Stage exact reviewed paths—never `git add .`—run `git diff --cached --check`, scan staged content for secrets/DSNs/tokens, and commit with the task's message.
8. If a reviewed diff changes, restage and repeat review. Serialize tests, reviews, migration rehearsal, and canary.

## 6. Backtest and promotion governance

- Freeze hypothesis, policy version, universe version, features, score, entry/stop/target, costs, and outcome semantics before opening the holdout.
- Use point-in-time universe and sector/industry observations; current membership must never masquerade as historical membership.
- Use chronological walk-forward/OOS evaluation with purging for the maximum hold. Never random-split market time series.
- Record every attempted parameter family and failed gate; do not report only winners.
- Require stability around chosen thresholds, sector/regime robustness, and low dependence on one ticker/date/fold.
- Preserve the approved breakout's existing immutable gate. New strategies are `research_only`, then at most `candidate` after governed historical evidence, and require explicit user approval plus forward shadow evidence before paper publication.
- Evaluate the allocator as a portfolio with overlapping positions and current-equity sizing. Report ruin honestly under the accepted policy; do not optimize rules after seeing the untouched holdout.
- Report underlying and option evidence separately and include stock-fallback frequency/reasons.

## 7. Definition of done

The pivot is complete only when:

1. Every recommendation candidate is from an immutable point-in-time snapshot of source-verified U.S. common stocks satisfying $200M-$15B market cap, price >=$3, and 20-session ADV >=$5M.
2. Foreign/ADR, OTC, ETF/ETP, leveraged/inverse, manipulation-risk, government-risk, unknown, stale, and denylisted names fail closed with reasons.
3. SPY/IWM/MDY are context-only and cannot be recommended.
4. The approved close-confirmed breakout has zero parity drift.
5. Pullback, VCP, and weekly industry/sector RS sleeves have versioned research evaluations and governed backtests; none auto-approves.
6. One allocator globally ranks/deduplicates candidates and enforces up to 20 concurrent recommendations, 5% defined risk each, 100% aggregate risk, and five per sector under concurrency.
7. Exact fresh read-only chain selection is preferred; unavailable/unsafe chains produce explicit underlying stock fallback without fabricating contracts.
8. Decision time is independent from evaluation time; all timestamps are timezone-aware; malformed numerics/containers and invalid/bounded OI/volume fail closed.
9. Evaluation/recommendation ticker, strategy, run, and durable chain snapshot provenance are cryptographically/relationally bound.
10. Unique indexes are installed by explicit idempotent migrations with populated-data preflight—not runtime DDL.
11. Underlying and option outcomes are separate, idempotent, and provenance-safe.
12. Portfolio reports quantify drawdown and accepted ruin risk under the actual approved sizing/cap policy.
13. Incomplete pipelines never emit clean no-trade; concise delivery names the signal date, instrument decision, risk, and fallback reason.
14. Fresh/bootstrap/upgrade migrations and the complete test suite pass in `wolfy_test`; independent reviews approve the exact staged snapshot.
15. No production mutation occurs before the release gate; the canary and rerun prove paper-only flags, zero broker actions, invariants, and rollback readiness.
