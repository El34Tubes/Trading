---
name: deterministic-paper-trading-systems
description: "Build and validate deterministic paper-trading recommendation systems: approved strategy gates, Postgres paper ledgers, outcome grading, and read-only summaries with no live execution."
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [paper-trading, recommendations, postgres, deterministic-strategies, finance, safety]
    related_skills: [test-driven-development, systematic-debugging]
---

# Deterministic Paper-Trading Systems

## When to use

Use this when building, auditing, or extending a paper-trading recommendation engine where trading decisions must come from deterministic strategy rows/signals rather than LLM judgment.

Typical triggers:

- User asks to continue stock/ETF recommendations or paper-trade logging.
- Adding a recommendation writer, paper ledger, outcome review, daily summary, or options-advisory layer.
- Promoting a strategy from research/candidate to paper-only recommendation flow.
- Connecting broker/account data in read-only mode for enrichment.

## Core safety contract

1. **No live execution by default.** Never place/cancel orders, move money, or alter real broker positions unless the user explicitly authorizes live execution in the current task.
2. **Strategy first.** Recommendations must trace to an approved deterministic strategy/signal row. LLMs may explain or summarize; they must not invent trades.
3. **Postgres as source of truth.** For durable paper recommendations/trades, use the project’s canonical Postgres tables. Do not silently fall back to SQLite for live paper state.
4. **Paper-only metadata is explicit.** Persist `paper_only=true`, `no_live_execution=true`, and `broker_order_submitted=false`/equivalent in notes or audit fields.
5. **Outcome grading is underlying setup quality.** Grade the stock/ETF setup against entry/stop/target/horizon, not the user’s option fill or real-account P/L.

## Recommendation droughts and strategy pivots

Before loosening gates, distinguish a verified no-trade from a governance block or an incomplete production path. A strategy present only on a development/review branch cannot create live paper recommendations; verify production seed/status, universe readiness, signals, exact-chain snapshots, allocator/writer invocation, scheduler, and delivery separately. Report the first broken layer instead of presenting an incomplete run as a clean no-trade.

When the user pivots strategy, interview the few choices that alter architecture: instrument fallback, universe and exclusions, strategy sleeves, allocation policy, per-position/aggregate paper risk, and rollout mode. Preserve approved formulas and add versioned research sleeves. Treat caps as configuration shared by every allocator/writer—not folklore embedded as “max 3”—and update concurrent-cap tests, summaries, and outcome metrics whenever the mandate changes.

Prioritize one useful vertical slice—ready universe through durable recommendation and outcome delivery—before adding more horizontal governance or strategy variants. See `references/recommendation-droughts-and-strategy-pivots.md` for the diagnostic checklist, strategy-fit guidance, interview order, fallback rules, and risk-contract migration checklist.

## Production promotion and publisher handoff

Treat promotion as a staged operational release, not a branch merge. Distinguish implementation, merged release snapshot, migration rehearsal, production migration, source-universe readiness, bounded canary, and scheduler activation. A green branch or shadow-only CLI is not production.

Use a clean release worktree when the live repository is dirty. Before any tests, capture protected production content **and a detailed schema inventory** (columns, indexes, constraints, triggers); a schema hash alone detects drift but cannot explain it. Scan merged tests for literal and indirect production connections, because a global test fixture does not override a hard-coded DSN. Stop if tests mutate either production data or schema.

Close the full migration dependency graph rather than trusting the declared migration tuple. Rehearse the exact pinned migrations twice on the dedicated test database and twice on a populated clone of production. Bind approval, independent review, migration hashes, canary, and scheduler to one immutable **code/configuration** snapshot fingerprint. Keep daily market-data/universe snapshot identity separate: a recurring publisher must create and persist a fresh source-backed data snapshot for each decision session rather than replaying one frozen canary snapshot forever.

Before production DDL, define expected migration deltas. Full-table hashes are unsuitable when a reviewed migration intentionally adds and backfills a column in a protected table; compare the projection of pre-existing columns separately, then verify the new column against its declared backfill invariant. Likewise, raw `pg_dump` hashes differ because modern dumps contain randomized `\\restrict` tokens—normalize those tokens or use canonical SQL/query hashes before treating a mismatch as data drift.

Enable only explicitly approved sleeves. A real canary must use the production database and a source-backed universe, prove durable caps/risk, exact-chain provenance or explicit fallback, zero broker writes, zero external delivery, and an idempotent rerun. A deterministic zero-candidate result is valid only after the complete universe and every terminal evaluation are durably evidenced; adapters must not reject that as an “empty canary.” Only then transfer ownership from the prior publisher, proving exactly one enabled publisher. Rollback disables the new publisher and restores the previous publisher/universe without deleting audit or recommendation rows.

See `references/production-paper-strategy-promotion.md` for the complete worktree, migration-dependency, populated-clone rehearsal, bulk universe-evidence, canary, cron handoff, and rollback procedure.

## Approved-gated recommendation writer pattern

A writer should:

1. Read deterministic signals for a specific `signal_dt` and optional `tickers`/strategy scope.
2. Join strategy metadata and require the full approval predicate, not just `status='approved'`.
   - Example durable predicate: `status='approved'`, `approval_scope='paper_only_no_live_execution'`, and `paper_recommendation_approval=true`.
3. Enforce the current portfolio contract cumulatively across all publishers. Never preserve a stale per-day constant when the mandate has moved to concurrent-position and aggregate-risk limits. For the current Wolfy mid/small-cap flow, the governing contract is up to 20 concurrent paper positions, exactly 5% defined paper risk each, up to 100% aggregate paper risk, and no more than five positions per sector; every sibling writer must share the same lock and durable-row accounting.
4. Insert `recommendations.status='paper_candidate'` with:
   - ticker/action/type;
   - entry baseline (EOD close);
   - stop/invalidation;
   - target/exit plan;
   - risk text;
   - strategy id/name and source signal in JSON notes;
   - option structure as advisory only when option data is missing.
5. Idempotency check must include already-processed states such as `paper_candidate` and `paper_logged`, not just newly-created candidate rows.

## Paper-trade logger pattern

A paper logger should:

1. Scope by `signal_dt`, `tickers`, or explicit recommendation IDs when possible; avoid unbounded global scans in tests and live smoke.
2. Read only paper candidate/logged recommendations tied to explicitly paper-approved strategies.
3. Compute paper quantity from risk amount and entry-stop risk.
4. Insert `paper_trades` with `status='open'`, entry date/price, stop, target, instrument metadata, and notes showing no broker order.
5. Mark source recommendations `paper_logged`.
6. Be idempotent by `recommendation_id` and report `skipped_existing` on repeat runs.
7. If a live smoke uncovers invalid candidates, tighten the upstream gate and clean only the invalid artifacts; keep valid paper artifacts if they are intended output.

## Governed revalidation and reactivation

For periodically revalidated paper strategies, preserve approval evidence separately from the newest observation:

- `approved_setup_outcome_gate` is the immutable user-approved gate and threshold contract.
- `latest_setup_outcome_gate` is the mutable result of the newest run; stamp every result with its evaluator mode and gate-definition version for auditability.
- Authorization, same-gate thresholds, and candidate eligibility must use only the immutable approved gate. Never implicitly promote/copy an unversioned latest result into authorization during revalidation; legacy migration is a separate audited operation that cannot reactivate a strategy.
- Require an explicit supported evaluator identity/version and the complete normalized threshold set. Invalid definitions force the current verdict to failed even for an already-approved strategy, allowing monthly demotion.
- Treat JSON metadata as untrusted typed input: require object/mapping containers before copying, exact JSON booleans in SQL (avoid casts on arbitrary text), strict canonical integer counts, finite bounded decimals, and closed-enum rule fields.
  - Require evaluator identity fields to be explicitly present; never infer a missing mode/version from current code. Legacy migration must be a separate audited write that cannot reactivate.
  - For integer identity/count fields, reject booleans before numeric comparison (`type(value) is int`, not merely `value == 1`), because Python treats `True == 1`.
  - Canonical gate definitions require exact key equality, not a required-key subset: reject unknown threshold/configuration keys rather than silently discarding them.
  - Keep the immutable approved definition separate from each mutable latest result, and stamp every latest result with the evaluator mode and definition version.
- Revalidate before monthly demotion, and distinguish `validation_run_date` from the actual market-data `validated_through` date.
- **Do not prefilter malformed gates out of governance.** Build the monthly governance population from paper-governance metadata/status and scheduling state, then normalize the immutable gate inside the fail-closed path. If SQL requires a valid gate before selecting a row, a fresh approved strategy with `latest_oos_verdict=true` can evade validation and remain approved after its gate becomes malformed. Invalid approved definitions must immediately stamp the current verdict failed and make the row demotion-eligible; only candidate reactivation eligibility should require a valid passing immutable gate.
- Downstream recommendation writers must not treat `status='approved'` plus paper-only flags as sufficient when governed gate validity/current verdict can change. Require the full current governance predicate, or ensure the governance transaction has demoted invalid rows before recommendation selection.
- Validate entry, stop, target multiple, and holding horizon fail-closed before counting a signal; key absence may default, but explicit invalid values may not truthiness-fallback.
- Scope integration tests and targeted maintenance by explicit strategy names/IDs so an unscoped test cannot revalidate unrelated production strategies.

See `references/governed-strategy-revalidation.md` for the fail/demote/recover lifecycle, provenance rules, metadata bounds, regression test, and orchestration safety pattern.

## Setup-outcome review gate

A post-trade review should:

1. Read open/closed paper trades and future OHLC bars after entry date.
2. Evaluate deterministic outcome over the intended horizon:
   - target hit;
   - stop/invalidation hit;
   - time stop/no follow-through;
   - MFE/MAE in R and percent;
   - classification such as successful continuation or stopped/invalidated.
3. Write `recommendation_outcomes` and update paper trade exit fields only once.
4. Keep the metric label explicit: `underlying_stock_technical_setup_not_option_fill_pnl`.
5. Never infer option contract P/L unless an option-paper ledger and option-chain data are explicitly implemented.

## Backtest versus forward options paper test

Do not treat paper trading as a prerequisite for testing whether an underlying setup had historical directional value. These answer different questions:

- **Chronological underlying backtest:** did the stock/ETF setup reach its target before invalidation, survive out of sample, and work across regimes?
- **Forward option-expression paper test:** could the signal be converted into a realistically priced, liquid option structure using the chain actually available at decision time?

For research-only options strategies, incomplete historical option validation need not block explicitly experimental paper recommendations when the user wants forward testing. Preserve these labels:

- `experimental_forward_test=true`
- `strategy_validated=false`
- `paper_only=true`
- `no_live_execution=true`
- `broker_order_submitted=false`

Never skip option-pricing safeguards merely because the trade is simulated. A useful forward test must capture exact contracts, timestamped bid/ask quotes, conservative fill assumptions, spread debit/credit, maximum loss/profit, liquidity, expiration, strikes, and subsequent marks. Midpoint-only fantasy fills teach little.

Maintain two separate outcome ledgers:

1. **Underlying thesis ledger:** target-before-stop, MFE/MAE in R, holding time, regime, breadth, sector, and volatility structure.
2. **Option expression ledger:** exact legs, entry/exit market, assumed fills, IV/Greeks when actually supplied, open interest/volume, spread width, defined loss, fees/slippage, P&L, and IV change.

Classify each observation as `setup_good/option_good`, `setup_good/option_bad`, `setup_bad/option_good`, or `setup_bad/option_bad`. This prevents rejecting a useful signal because of poor contract selection, or crediting a weak signal for a volatility-driven option gain.

When no trustworthy historical chain exists, do not fabricate one from current snapshots. Backtest the underlying historically and collect exact option-chain evidence forward. Comparing multiple paper structures on the same qualifying signal (for example, a long call versus a call debit spread) is a useful experiment, provided neither is represented as a live trade. Do not force the same structure across all stocks: run every qualifying setup through the same deterministic selector, then permit stock-specific outcomes such as long call, target-aligned call debit spread, or no tradable option structure. Keep the first version bounded to structures that express the existing directional thesis; adding condors, calendars, credit spreads, butterflies, or opposite-direction trades is a separate strategy family, not a harmless selector extension.

For a bounded bullish selector, prefer ATM or modestly ITM long legs when trustworthy delta is unavailable; otherwise target-state leverage can incorrectly favor an OTM lottery-ticket long. Score exact contracts using conservative fills, target-state payoff, maximum loss, quote quality, and target alignment. Preserve every candidate and rejection reason. If one indivisible contract exceeds the paper risk budget, reject it rather than rounding up, weakening the risk rule, or inventing fractional contracts.

### Adversarial options-paper release gate

Treat selector/evaluation JSON as untrusted at the writer boundary: independently validate quote provenance and age, finite positive economics, leg relationships, DTE, moneyness, multiplier, and maximum-loss arithmetic rather than trusting status/policy labels. The strongest pattern is to persist the normalized input contracts plus a required timezone-aware decision timestamp, then have the writer rerun the canonical selector from the source signal's entry/target/date and compare the selected structure, legs, fills, payoff, and maximum loss exactly. Missing raw contracts, missing/naive decision time, stale quotes, supplied market dates that disagree with a market-timezone-derived date, and any recomputation mismatch must fail closed.

Reject booleans as counts and reject noncanonical, nonfinite, or malformed numerics with deterministic reasons instead of batch-breaking exceptions. For integer liquidity/multiplier fields, accept actual integers or a deliberately documented canonical integer-string grammar; reject fractional strings and float-like forms such as `"10.0"`. Derive U.S. option quote `market_date` from `quote_at` in `America/New_York`; never trust a caller-supplied market date to make an old quote appear current.

Whole-contract sizing and a one-contract cap are separate policies. If the strategy only caps total defined loss, quantity may exceed one when `floor(risk_budget / canonical_max_loss_per_contract) > 1`; persist effective risk fraction, per-contract maximum loss, quantity, and total maximum loss, and assert `total_max_loss <= risk_budget`. Enforce quantity `<= 1` only when the strategy contract explicitly says so.

Enforce daily caps cumulatively across invocations and across all qualifying paper recommendation types/statuses for the signal date. Before counting and inserting, acquire a transaction-scoped advisory lock keyed to the global paper-recommendation date; compute remaining capacity from durable rows, not the current invocation's list. **Every sibling writer capable of creating a cap-consuming row must take the same date lock and enforce the same cumulative cap**—locking only the aggressive/experimental writer still permits an approved writer to create a fourth row after the locked transaction commits. Back idempotency with a canonical partial unique index over ticker plus JSON signal date and strategy name for active paper states, and use conflict-safe insertion. Before creating that index on an upgraded database, detect pre-existing duplicates and fail with an actionable migration error rather than deleting or arbitrarily merging rows. Test repeated disjoint calls, mixed approved/experimental rows, same-key retries, same-writer races, and mixed-writer two-connection races where one transaction holds its insertion uncommitted while the other writer starts.

For multi-blocker hardening, finish one vertical RED→GREEN slice at a time (selector validation → profile wiring → writer recomputation → transactional constraints), batch independent reads/tests, and reserve enough tool budget for final focused tests, the broader suite, diff review, and production before/after invariants. Do not begin a new schema/concurrency slice if it cannot be implemented and verified in the remaining session; stop at a coherent green checkpoint and report exact unfinished work instead.

See `references/adversarial-options-paper-release-audits.md` for concrete forged-evaluation, stale-quote, malformed-number, one-contract, repeated-call, and concurrent-writer probes.

A free delayed option-chain feed can support after-close forward paper evaluation, but not execution. Fetch only for already-qualifying signals. Preserve the raw UTC snapshot timestamp and derive a New York `market_date`: an after-close U.S. snapshot can be next-day UTC while still belonging to the prior market session. Treat zero IV/Greeks from deep contracts as unavailable placeholders when the feed uses zeros to signal missing analytics. Retain delayed status, source URL, raw chain, normalized contracts, and a live schema/availability smoke because public website feeds have no contracted SLA.

See `references/options-backtest-versus-forward-paper-testing.md` for the decision framework and minimum evidence schema. See `references/deterministic-stock-specific-option-structure-selection.md` for the bounded 7–35 DTE long-call-versus-debit-spread selector, conservative fill model, audit ledger, experimental gate override, and verification checklist. See `references/free-delayed-options-forward-evaluation.md` for the Cboe delayed-chain normalization, market-date, bounded-fetch, and live-source verification pattern.

## Paper-ledger learning metrics

Useful non-destructive columns for paper trades:

- `max_adverse_excursion` — worst adverse move in R.
- `exit_efficiency` — realized R divided by MFE R; not always 1.0 even for target hits if price overshot target before exit.
- `stop_distance_atr` — entry-stop distance divided by ATR at entry date, when features data exists.

Add columns with compatibility migrations (`ADD COLUMN IF NOT EXISTS`) or SQLite column adders in tests. Backfill existing closed trades from stored outcome JSON when possible.

## Market-data source evaluation

When researching or selecting low-cost OHLCV sources for deterministic technical signals:

1. **Separate platform quota from dataset entitlement.** A generous free API rate limit does not mean the desired U.S. equity dataset is free; verify the product page or endpoint metadata for premium status.
2. **Prefer first-party, current evidence.** Cite official plan, endpoint, adjustment, corporate-action, and terms pages. Treat old tutorials and third-party limit summaries as discovery leads only.
3. **Record signal-relevant semantics, not just price.** Capture historical depth by interval, adjustment behavior for OHLC and volume, separate split/dividend events, venue coverage, delayed-vs-real-time status, symbol-change handling, survivorship characteristics, and retention/redistribution rights.
4. **Distinguish single-venue from consolidated feeds.** IEX-only data may be acceptable for basic price-direction checks, but not as a substitute for SIP data in volume, liquidity, precise high/low, gap, or execution-sensitive signals.
5. **Label unknowns explicitly.** If documentation does not establish whether bars are raw or adjusted, do not infer it from sample output. Require a known-split/dividend reconciliation before production use.
6. **Inspect client-rendered official pages when necessary.** If pricing or limits are populated by JavaScript, inspect the page's own embedded state or shipped bundle, and still cite the public official page rather than a temporary asset URL.
7. **Assess operational and legal fitness separately.** An endpoint can be technically accessible yet unsuitable because it is unofficial, personal-use-only, non-commercial, anti-automation protected, lacks an SLA, or restricts retention of downloaded/derived data.
8. **Assign a bounded role.** Classify each source as canonical, paid secondary/fallback, asynchronous validation, corporate-action cross-check, research bootstrap, or unsuitable. Never silently promote a validation source into canonical history.
9. **For event-calendar audits, separate four questions:** whether an endpoint is documented, whether the configured credential is entitled, whether the repository has a domain client rather than only a generic HTTP helper, and whether the durable schema preserves point-in-time revisions. Use bounded no-write probes and never print authenticated URLs or keys.
10. **Do not confuse similarly named datasets.** Ticker-change “events,” splits, and dividends do not satisfy an earnings-calendar gate. Verify actual event types and required fields such as date, BMO/AMC timing, confirmation/status, provider ID, provider update time, observation time, and source provenance.

See `references/us-equity-market-data-source-evaluation.md` for a compact provider-comparison checklist and current-source caveats learned from Alpaca, Nasdaq Data Link, Stooq, Yahoo/yfinance, and Finnhub research. See `references/earnings-calendar-source-capability-audits.md` for a read-only entitlement/client/schema audit workflow and Massive/Polygon earnings endpoint distinctions.

## Options support rule

For users who prefer options expression, keep options advisory until chain data is available and deterministic selectors are tested. Model the instrument policy explicitly:

- `defined_risk_options_only`: a missing/unsafe chain yields no position; never substitute equity.
- `options_preferred_underlying_fallback`: evaluate the exact chain first, then deterministically use the underlying stock/ETF when no safe option structure exists; persist the rejection and fallback reason and track instrument outcomes separately.

Once a policy is selected, enforce it end to end rather than allowing different writers to improvise different fallbacks.

When the user requests a maximally aggressive options profile, create a separate versioned `research_only` experimental strategy instead of weakening an approved strategy in place. Loosen opportunity gates (volume, relative strength, regime, breadth, sector confirmation, bounded stop width, and modest OTM eligibility), but never loosen evidence and loss-control gates (exact fresh quotes, standard contracts, defined maximum loss, whole-contract sizing, the currently approved portfolio cap, and no live execution). Do not hard-code equity fallback as either forbidden or mandatory: bind it to the explicit versioned instrument policy (`defined_risk_options_only` versus `options_preferred_underlying_fallback`) and enforce that policy in the selector, writer, outcomes, and delivery. Persist the effective risk, aggregate-cap policy, configured holding horizon, and fallback reason downstream; do not leave caller-requested values or legacy hard-coded text in recommendation audit records. See `references/aggressive-options-paper-profiles.md` for the reusable profile, parameterization pattern, pitfalls, and verification matrix.

Core options-only requirements:

- Store preferred structure such as `2-3 week slightly OTM call spread`.
- Missing option-chain data must be represented as missing/stale, not fabricated.
- Do not let an LLM invent Greeks, IV, bids/asks, or fills.
- Broker/MCP integrations should start read-only for chain, tradability, account/position, and liquidity enrichment.
- A strategy marked `defined_risk_options_only` must reject equity instruments and equity fallback, require an actual option structure, and retain option-liquidity/spread and defined-risk gates.
- Higher underlying volatility may be allowed, but volatility must be explicit and structural: favor contraction followed by orderly expansion; reject chaotic gaps/ranges/wicks. VIX and realized volatility can be context rather than arbitrary hard caps.
- Add new volatility logic as a separate `research_only` strategy variant. Do not silently loosen an approved production strategy before chronological out-of-sample validation.
- Current option-chain snapshots are not historical IV/Greeks data and must not be used to backfill a strategy test.

## Point-in-time technical-data discipline

For breadth, volatility regimes, short data, and public market-structure feeds:

- Join backtests using `available_at <= decision_timestamp`, not observation or settlement date alone. Data published after the close is normally next-session information.
- Never fetch a current webpage during a historical replay and relabel it with the replay date. Current-page feeds should run only in the current-session ingestion path.
- Historical breadth requires point-in-time universe membership. If membership history does not exist, snapshot the current eligible universe and collect breadth forward-only; explicitly block historical backfill rather than applying today's survivors backward.
- Preserve definition/version boundaries for series such as put/call ratios. Missing or stale context must remain unavailable, not silently become zero.
- Nasdaq short interest is usable only after dissemination/publication, not its settlement date. FINRA short volume is flow through FINRA facilities, not consolidated shorting or outstanding short interest.
- VIX and realized volatility are market/underlying context; never label either as ticker option IV.
- If using a local NYSE calendar, version it and parity-test the full supported range against a pinned exchange calendar. Do not reuse generic federal-holiday observation rules blindly: when New Year’s Day falls on Saturday, NYSE remains open on the preceding Friday (for example, 2021-12-31); Sunday New Year shifts to Monday.

## Schema and migration discipline

When runtime code creates durable tables, keep schema ownership aligned:

1. Add a new non-destructive forward migration; do not rewrite an old applied migration.
2. Mirror the DDL in the runtime `ensure_*_schema()` function.
3. Update the canonical initialization SQL only after isolating any unrelated dirty edits; never overwrite or accidentally commit someone else's pending schema work.
4. Add migration tests or execute the idempotent migration with `ON_ERROR_STOP=1` and verify the expected tables/indexes. If the database role cannot create a temporary database, validate non-destructively against the existing schema and report that limitation accurately.
5. Use `CREATE TABLE/INDEX IF NOT EXISTS` and additive migrations. Strategy seeds must remain `research_only` unless a separate evidence gate approves promotion.

## Testing checklist

- Write failing tests first for new behavior.
- Route every state-mutating Postgres test through a dedicated test database and a connection helper that always rolls back. Fail closed unless `current_database()` is the exact allowed test database.
- Provision the test database idempotently and guard schema application with an advisory lock. Apply the canonical initialization SQL twice with `ON_ERROR_STOP=1` as a separate idempotency check.
- Use collision-resistant, future-dated fixture tickers, strategy names, and dates. Rollback is the primary isolation mechanism; cleanup SQL may support assertions but must not be the safety boundary.
- Inventory indirect live writes as well as literal DSNs: imported default DSNs, connection adapter aliases, subprocess arguments, environment fallbacks, and ancillary metrics/telemetry writers can bypass a literal-string search.
- Capture the exact production baseline **before any test command**. Re-query immediately after focused tests, migrated integration suites, and the full suite so a mutating phase is identifiable.
- If any protected production metric changes, stop immediately: do not stage, commit, or repair live data without explicit authorization. A green suite does not prove isolation; only unchanged before/after live queries do.
- Keep pure configuration tests that assert production defaults unchanged; distinguish assertions about a default DSN from code that opens that DSN.
- Include unrelated/pre-existing rows so global-scan bugs are caught.
- Assert full safety metadata (`paper_only`, `no_live_execution`, no broker orders).
- Seed the full approval predicate in isolated tests, not only `status='approved'`; clean test databases do not contain production metadata that old tests may have accidentally relied on.
- Assert idempotency by immediately running the writer/logger/reviewer twice.
- Test replay/current-ingestion separation, publication lag, stale/missing context, and refusal to backfill breadth without membership snapshots.
- Run focused tests, full suite, compilation, diff checks, dry-run orchestration, and a transaction-rollback signal-generation smoke.
- Verify the committed artifact from a clean export in addition to the dirty working tree.
- Commit only relevant files; secret-scan staged diff.
- Treat an independent review verdict as bound to the exact staged snapshot it inspected. Freeze `git diff --cached --binary` to a uniquely named patch file and record its SHA-256 before dispatch; have the reviewer read that file rather than a moving index. Before commit, regenerate/hash the staged patch and require an exact match. Any edit or restage invalidates the verdict and requires a new frozen snapshot/review. Remove temporary review artifacts after commit.

See `references/postgres-test-database-isolation.md` for a reusable harness design, migration inventory, phased baseline proof, and stop conditions.

## References

- `references/production-paper-strategy-promotion.md` — clean release worktrees, production baseline proof, migration dependency closure, populated-clone rehearsal, source-backed universe construction, exact-snapshot canary, single-publisher handoff, and non-destructive rollback.
- `references/recommendation-droughts-and-strategy-pivots.md` — classify no-trade versus governance/pipeline failure, diagnose recommendation delivery end to end, interview strategy pivots, migrate caps/risk contracts, and prioritize a useful vertical slice.
- `references/aggressive-options-paper-hardening.md` — compact release checklist for separate aggressive profiles, executable-path wiring, strict quote/numeric validation, writer-side selector recomputation, transactional daily caps, and aggregate defined-loss sizing.
- `references/governed-strategy-revalidation.md` — immutable approval versus mutable latest gates, fail/demote/recover behavior, data-through provenance, fail-closed signal metadata, production-safe test scoping, and paper lifecycle orchestration.
- `references/wolfy-paper-recommendation-engine-2026-08.md` — concrete Wolfy session architecture and task sequence that produced approved recommendations, paper logging, setup review, and daily summaries.
- `references/us-equity-market-data-source-evaluation.md` — evidence checklist, provider-specific caveats, and signal-role rules for free/low-cost U.S. OHLCV research.
- `references/earnings-calendar-source-capability-audits.md` — bounded read-only provider entitlement probes, repository client-versus-transport inspection, earnings provenance schema requirements, and Massive/Polygon event-endpoint distinctions.
- `references/free-volatility-options-strategy-extension.md` — free Cboe/FINRA/Nasdaq/Treasury ingestion roles, lookahead-safe provenance, volatility-structure design, options-only gates, and clean verification workflow.
