---
name: wolfy-recommendation-engine
description: Build, validate, and operate Wolfy's deterministic Postgres-backed EOD paper recommendation engine without live execution.
version: 1.2.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [wolfy, trading, recommendations, postgres, paper-trading, eod, safety-gates]
    related_skills: [test-driven-development, systematic-debugging]
---

# Wolfy Recommendation Engine

## When to use

Use this when working on Wolfy's strategy validation, deterministic EOD signals, approved paper recommendations, Postgres paper-trade logging, or daily recommendation/ledger summaries.

Typical triggers:

- User says to continue recommendations, paper trading, strategy validation, or Wolfy trade logging.
- Editing `/root/.hermes/wolfy/eod_signals.py`, `eod_backtest.py`, recommendation writer/logger tests, or `paper_trades` flows.
- Checking whether an actionable recommendation or paper trade may be created.
- Adding broker/RH/Robinhood enrichment to recommendations.

## Non-negotiable safety rules

1. No live trading, broker order placement, order cancellation, or money movement unless the user gives a new explicit authorization in the current session.
2. Paper recommendations and `paper_trades` are Postgres-backed. Do not add SQLite fallback for this flow.
3. LLMs may summarize/explain/review, but deterministic code must create the signal/recommendation/trade rows.
4. Recommendations must be traceable to strategy, signal date, setup evidence, entry baseline, stop/invalidation, target/exit plan, and risk sizing.
5. Treat user-approved paper flow as separate from live trading. Bypassing Sentinel/Yang for paper does not authorize live execution.

## Paper-flow governance

`liquid_rs_breakout_close_confirm_1r` has prior user approval for the paper-only flow, but its **current live status must always be read from Postgres**. Monthly revalidation can demote it to `candidate`; do not describe it as currently approved from skill text or memory alone.

A strategy is eligible for paper recommendations only if all of these hold:

```text
strategies.status = 'approved'
strategies.metadata.approval_scope = 'paper_only_no_live_execution'
strategies.metadata.paper_recommendation_approval = true
signal direction is long/buy
recommendation notes paper_only=true and no_live_execution=true
```

Do not rely on `status='approved'` alone. Tests or old live state can accidentally leave a research strategy approved; require the explicit metadata scope before creating paper recommendations or paper trades.

## TDD workflow

Follow strict TDD for behavior changes:

1. Add/patch a focused failing test in the relevant Wolfy test file.
2. Run only that test and confirm it fails for the expected missing behavior.
3. Implement the smallest production change.
4. Run the focused test, then the relevant file tests, then the full suite.
5. Run a live smoke only after tests pass; keep it scoped and paper-only.
6. Commit only reviewed Wolfy files with a staged secret scan.

Preferred commands:

```bash
cd /root/.hermes/wolfy
python3 -m pytest test_eod_signals.py::<test_name> -q
python3 -m pytest test_eod_signals.py -q
python3 -m pytest -q
```

## Postgres paper recommendation writer lessons

The approved recommendation writer should:

- query `signals` joined to `strategies` for a specific `signal_dt` and optional ticker scope;
- use only explicitly paper-approved strategies;
- cap daily rows, currently max 3;
- insert `recommendations.status='paper_candidate'`;
- include `paper_only`, `no_live_execution`, `paper_entry_baseline='eod_close'`, strategy ID/name, and source signal in `notes`;
- set `recommendation_type='equity_plus_option_spread_when_data_exists'`;
- make options liquidity advisory metadata, not a hard block;
- accept optional Robinhood/broker read-only enrichment after deterministic signals exist, storing tradability, halt, quote/spread, price-drift, account-exposure, earnings-window, fundamentals, and option-spread metadata in notes while keeping `broker_order_submitted=false`;
- check existing rows using statuses `paper_candidate` and `paper_logged` so reruns do not recreate already-logged recommendations.

### Robinhood MCP enrichment pattern

Use Robinhood MCP as a read-only broker-context layer after Wolfy has already selected approved deterministic paper candidates. It can warn/block/enrich recommendations, but it must not create the signal or submit live orders. Expected useful surfaces: `get_equity_tradability`, `get_equity_quotes`, `get_equity_price_book`, `get_equity_fundamentals`, `get_earnings_calendar`/`get_earnings_results`, positions/orders, and options chain/instrument/quote reads. Keep `place_*`, `cancel_*`, and `exercise_*` tools hard-blocked unless the user gives explicit current-session live-trading authorization. See `references/robinhood-broker-enrichment-2026-08.md` for the implemented payload contract and tests.

## Postgres paper-trade logger lessons

The paper logger should:

- create `paper_trades` only from `paper_candidate`/`paper_logged` recommendations tied to explicitly paper-approved strategies;
- be idempotent by `paper_trades.recommendation_id`;
- accept `signal_dt` and `tickers` filters so tests/live smokes do not scan unrelated legacy candidates;
- mark source recommendations `paper_logged` after insert;
- write `status='open'`, `instrument='equity_fallback_plus_option_spread_advisory'`, `data_source='approved_deterministic_recommendation'`;
- include `broker_order_submitted=false`, `paper_only=true`, and `no_live_execution=true` in `paper_trades.notes`;
- block rows with missing/non-positive entry/stop risk instead of logging nonsense;
- return `broker_orders_created=0`.

Default paper sizing currently uses 5% risk of a $5,000 paper account unless the user changes it.

## Postgres integration-test isolation

New and migrated Wolfy integration tests must use the dedicated `wolfy_test` harness, not the live `wolfy` database. Parse and validate `WOLFY_TEST_POSTGRES_DSN`, require the exact database name `wolfy_test`, re-check `current_database()` before schema/DML work, provision schema idempotently, and wrap each test in an explicit rollback connection. Do not use `with psycopg.connect(...)` as the rollback boundary because successful context exit commits. Apply schema outside the per-test transaction, and keep helpers that commit internally out of rollback-scoped tests until refactored.

Do not assume a test is isolated merely because its assertions use temporary SQLite or an explicit `wolfy_test` connection. Legacy helpers may dual-write through a secondary default Postgres sink (for example, recommendation/scanner compatibility writers). Install a session-wide pytest safety fixture that forces every implicit `WOLFY_POSTGRES_DSN` to the validated test DSN, then search for default connection factories and dual-write call sites—not only literal DSNs. Add an end-to-end regression that invokes a real dual-write helper and proves the live production count is unchanged. Treat a changed production baseline as a revision gate: identify row provenance/timestamps first, never delete rows to make the count match, expand isolation coverage, establish the new observed baseline, and rerun the suite serially.

A mature live database can hide clean-bootstrap SQL ordering defects. If fresh `wolfy_test` provisioning exposes a relation/column referenced before creation, fix the canonical idempotent schema ordering rather than adding a harness-only workaround. See `references/dedicated-postgres-test-harness.md` for strict TDD slices, bounded local peer-auth provisioning, extension setup, advisory locking, migration order, rollback semantics, and verification gates.

If a file-local rollback patch passes focused tests but the full suite still mutates governance state, do not commit the partial fix. Preserve post-failure evidence, restore only proven row/column deltas from the pre-test backup, bisect committing test files by complete-row hashes, and treat unrelated schema-contract failures as separate blockers rather than bundling them into the isolation task. See `references/full-suite-governance-leak-isolation.md`.

## Legacy live DB test pitfalls

Any integration tests not yet migrated still run against the live Wolfy Postgres database and must be treated as production-scope operations:

- Migrate to the dedicated test harness as the first choice. Until migration is complete, use future-dated `ZZ...` tickers and unique unit strategy names with strict cleanup.
- Any function that scans or mutates strategies globally (monthly revalidation, demotion, cleanup, migration, outcome review) must accept an explicit strategy/ticker/date scope. Integration tests must pass that scope; never call global maintenance unscoped from a live-DB test.
- Capture and restore only the exact rows/fields the test owns. Do not reset all strategy statuses or governance metadata.
- Clean unit-test tickers in foreign-key order from `recommendation_outcomes` when applicable, `paper_trades`, `recommendations`, `setups`, `signals`, `features`, `prices`, and `universe_symbols`.
- Put cleanup in `finally` or use rollback so a failed assertion/import/type error cannot strand fixtures.
- Never delete real SPY benchmark history; limit SPY cleanup to isolated future fixture dates.
- If a test temporarily sets a generic strategy to `approved`, restore the exact previous state. Production code must still require explicit metadata approval scope so accidental status state cannot leak into live recommendations.
- After any test involving global governance, query the real approved strategy and latest backtest/research-log rows to detect unintended production mutation before proceeding.
- Never run DB-integrated tests, reviewer probes, and a canonical live validation concurrently. Reviews may execute staged integration tests or direct probes against live Postgres and finish after the smoke, overwriting validation dates or gate observations. Serialize tests → reviews → commit/push → final scoped live revalidation → read-back verification.
- If validation dates or samples regress unexpectedly, inspect recent `research_log` revalidation entries to identify an older reviewer/test cutoff, then restore state by rerunning the canonical paper-only validation serially. Do not patch dates directly.

## Recommendation-readiness audit

When asked for today's recommendations, do not jump directly from an empty recommendation table to "no setup." Audit the full chain:

For broad status questions such as “where are we at?”, follow `references/live-status-snapshot-audit.md`. It adds live clock/cron/budget/task/git checks, date-by-date coverage comparison, future-fixture filtering, approved-strategy signal isolation, and the rule that cron success does not prove data completeness.

1. current New York date versus latest price/feature date;
2. live strategy status and explicit paper-approval metadata;
3. fresh deterministic revalidation state;
4. scheduled signal-universe coverage versus the validation universe;
5. whether cron invokes the recommendation writer, paper logger, and outcome reviewer after signal generation.

Distinguish these outcomes clearly:

- **Clean no-signal:** data and pipeline are complete, strategy is eligible, and zero qualifiers passed → recommend no trade/cash.
- **Pipeline incomplete:** stale/delayed data, candidate strategy, narrow/unexpected universe, or missing writer/logger wiring → say no trustworthy recommendation is available and name the blocker.

The free/delayed Massive plan normally uses the previous business day because current-day aggregate requests may be unauthorized. Do not call expected T+1 data a failed ingest, and do not force current-day mode without verified provider entitlement.

### Weekend and delayed-session catch-up

Do not interpret missing Friday bars during Friday's scheduled run as requiring a wait until the following Friday. Under the safe previous-business-day policy, Friday bars may become available on Saturday or Sunday. When the user wants the earliest trustworthy recommendation:

1. verify per-date coverage against the exact configured `CORE_EOD_UNIVERSE` symbol set rather than trusting a global `max(dt)` or a remembered universe count;
2. run a representative no-write Massive probe and require the intended session date for every probe symbol;
3. if available, run the stable five ingest shards immediately, then verify complete prices/features set equality;
4. inspect point-in-time universe-snapshot availability before signal generation. An explicit replay must fail closed when its historical snapshot is absent; never fabricate one. For a normal weekend catch-up where the intended session is now the verified latest completed session, run the normal wrapper without `--signal-dt` so it records current source/universe availability before breadth and signals;
5. read back all-strategy signals separately from explicitly paper-approved strategy signals, recommendations, trades, and broker safety flags;
6. report a recommendation only if the approved deterministic gate qualifies—otherwise, after complete coverage and a successful chain, return a verified no-trade result.

Prefer bounded shard jobs for long catch-ups. If the host interpreter lacks optional `psycopg`, an ephemeral `uvx --with 'psycopg[binary]' python ...` invocation is an acceptable setup fallback; do not modify the system Python or memorialize the missing package as a permanent limitation. See `references/delayed-eod-weekend-catchup-and-immediate-recommendation-rerun.md` for the operational recipe.

Monthly governance must re-run the same gate before demotion and keep validation-run time distinct from the backtest's final observation date. A monitor that only demotes cannot maintain an approved recommendation flow by itself.

### Immutable gate fail-closed rules

Keep the immutable approved authorization gate separate from the latest performance result. Normalize approval metadata canonically: require explicit evaluator identity/version, exact threshold keys and strict value types/ranges, reject malformed JSON shapes, and never truthiness-fallback after an explicitly invalid signal parameter. Monthly selection must route governed approved strategies through normalization even when their gate is malformed or fresh; otherwise SQL prefilters can hide invalid approvals from both revalidation and demotion. Candidates may retry only from an intact canonical approved gate. Compare untrusted JSON booleans exactly rather than casting arbitrary text.

See `references/immutable-gate-fail-closed-validation.md` for canonical parsing rules, monthly selector design, malformed-metadata handling, the regression matrix, and snapshot-specific release review.

See `references/recommendation-pipeline-readiness-and-delivery.md` for the complete readiness chain, revalidation semantics, universe check, downstream job order, and user-facing decision rules.

## Expanding daily recommendation opportunity safely

When the user wants more recommendations, do not begin by relaxing a validated gate or adding indicator variants. First classify the bottleneck as historical depth, daily expected-session freshness, event/security provenance, validation integrity, opportunity breadth, or strategy-family scarcity. Once bounded history is fully accounted for, stop treating more historical pulls as the default answer; incomplete daily coverage is a readiness problem, not a history problem.

Prefer this order: complete-session readiness → earnings/corporate-action/bar-quality provenance → controlled broad-universe expansion with golden parity → gate-attribution ledger → walk-forward/multiple-testing/survivorship controls → one orthogonal research setup → exact read-only option decisions → explainable ranking model only after sufficient forward evidence. A technical-options feature table is not evidence that exact chain evaluation is wired.

A hard budget gate remains an implementation stop unless the user explicitly chooses a bounded interactive override. Record that override in task/run metadata without changing the global threshold, keep scheduled jobs gated, and preserve the isolated-worktree, dedicated-test-DB, TDD, independent-review, and production-invariant requirements for the named slice.

Audit the scheduled universe against the data-ready/validation universe, preserve the approved setup with golden parity tests, and expand through staged shadow caps using point-in-time U.S./liquidity/security-identity gates. See `references/recommendation-optimization-priority-gates.md` for the complete decision tree, completion accounting, and bounded override protocol.

For delayed/free EOD sources, schedule a next-business-day premarket catch-up so the latest completed session is evaluated before the next open. Resolve sessions with an exchange calendar, retry only missing symbols in bounded shards, and require benchmark plus declared broad-universe coverage before publication. A partial run is `pipeline_incomplete`, not a clean no-signal result. Gate readiness before external context fetches, signal subprocesses, recommendation writers, or paper-ledger mutations; keep current-session and exact-date replay paths separate. See `references/eod-readiness-fail-closed-implementation.md` for the typed contract, TDD matrix, exact-commit review procedure, full-range independent calendar differential, New Year's Saturday regression fixture, and release gates.

For earnings/event safety, probe the live provider entitlement before building an ingest, preserve source/availability/revision provenance, and treat missing coverage as `earnings_unknown` rather than no event. A current calendar supports a forward veto but not historical PEAD validation. See `references/earnings-calendar-source-entitlement-and-fail-closed-contract.md` for endpoint-probe discipline, observed provider fit, and the no-source fail-closed behavior.

Record deterministic gate evaluations for every run/ticker/strategy, including near-miss reasons, before tuning anything. Treat the ledger as an authoritative state machine: freeze deterministic run identity from insertion, make published parent/child evidence immutable, enforce canonical reasons in Postgres as well as Python, and test populated partial-schema upgrades—not only clean bootstrap. Direct-SQL and concurrency probes are required because helper-level validation cannot protect the authoritative database contract. See `references/auditable-postgres-ledger-release-gates.md` for the adversarial schema, migration, JSON/date, immutability, and review checklist.

Before implementing the point-in-time U.S./liquidity/security-risk gate, audit every universe producer and consumer plus the live read-only schema. Do not treat mutable `universe_symbols`, current active-only provider pulls, ticker/name heuristics, one-session dollar volume, or current membership snapshots as point-in-time identity evidence. Store append-only source observations with effective dates, `available_at`, and provenance; use exact provider type/locale/market/exchange/currency fields; fail closed on unknown/conflicting identity; make the user denylist absolute; and shadow-compare classifications before changing current state. See `references/point-in-time-security-eligibility-gate.md` for the full audit workflow, migration hazards, provider contract, and RED matrix.

Add orthogonal setup families in research-only lanes, validate underlying and option outcomes separately, and use one cross-strategy allocator for portfolio-wide count, heat, duplicate, sector, and correlation constraints. Instrument-expression policy is plan-specific: older plans may require `long_call | call_debit_spread | no_option`, while an explicitly approved pivot may prefer exact safe options and retain a qualified underlying as `underlying_stock_fallback`. Record which policy supersedes the other; never let legacy compatibility fields decide implicitly.

For a mid/small-cap stock-only pivot, reconcile the accepted plan before writing tasks: mark foundations as reuse/adapt/supersede/defer, resolve ETF-rotation conflicts by using SPY/IWM/MDY as context and rotating among eligible stocks by industry/sector, close partial-options review blockers first, and deliver an underlying-only shadow vertical slice before adding research sleeves. All recommendation writers must share one transaction-scoped global cap lock and recount; `decision_at` must come from the immutable run and remain independent from evaluation/fetch/insert time; malformed numerics, containers, naive timestamps, and negative/overflow OI/volume fail closed; ticker/strategy/evaluation must bind to durable chain-snapshot provenance; and unique indexes belong in explicit populated-data-safe migrations rather than runtime schema helpers. When aggressive paper risk is explicitly accepted, measure drawdown and ruin under the approved sizing/caps instead of silently adding a stricter heat limit. See `references/mid-small-cap-multi-strategy-pivot-planning.md`.

Before broad implementation in Wolfy's operational repository, isolate a clean worktree and establish a dedicated Postgres test database/rollback harness. Surface material user trade-offs—latency/provider cost, universe cap, ETF policy, setup hypothesis, concentration, earnings-data cost, options liquidity, forward evidence, aggregate heat, coverage threshold, and any bounded budget override—rather than silently choosing permanent policy.

When the user explicitly accepts all documented recommended defaults and asks for autonomous execution, record that acceptance in the tracked plan, create a durable task ledger, and execute bounded TDD/review/commit checkpoints until every release gate passes. Preserve the original dirty workspace by hashing its status before and after worktree creation. Treat accepted defaults as policy approval only within the plan: they never imply live trading, broker writes, destructive cleanup, paid-data purchases, or bypassing unavailable-source gates. Persist progress in Git and the task ledger so a disconnected session resumes by inspection rather than conversational memory.

See `references/daily-multi-setup-evaluator-planning.md` for the detailed scheduling, staged-universe, near-miss, setup-portfolio, options/allocation, testing, and user-decision pattern. See `references/accepted-plan-autonomous-execution.md` for the durable worktree, per-task TDD/review loop, disconnection recovery, and serialized release/canary order.

## Scheduled delivery policy

For Wolfy, keep routine health/watchdog/accounting/autorepair/scanner output local. Deliver to Discord/origin only actual progression, actionable recommendations, user-required decisions/approvals, or exceptional blockers requiring user action. Do not deliver Clerky activity reports; its local Kanban allocator may continue. Prefer silent empty stdout for script-only jobs with nothing actionable.

## Live smoke pattern

After tests pass, use a tightly-scoped live smoke:

1. Query counts before: `paper_candidate`, `paper_logged`, `paper_trades`, `open_paper_trades`.
2. Dry-run recommendation writer/logger first.
3. If live-running, use the latest approved-strategy signal date and max 3 rows.
4. Verify rows have `no_live_execution=true` and `broker_order_submitted=false`.
5. Verify rerun skips existing rows rather than duplicating.
6. Reset accidental generic strategy approvals back to research-only if encountered.

## Task board and git hygiene

- When the deterministic budget gate blocks an optimizer run, perform durable **plan-only closure** rather than silently exiting: create/claim a dated accounting task, start its linked run, record the complete KPI set, commit only the optimization ledger note, and finish the task/run after read-back verification. Do not claim or modify the queued implementation task while blocked. See `references/budget-gated-optimizer-plan-only-closure.md` for the exact sequence, DoD, metric-labeling rules, CLI/SQL pitfall, and concise report format.
- Every optimizer orientation and verification budget probe must use `budget_gate.py --no-record`, including the first Phase-0 check. A bare invocation writes unlinked `loop_metrics` rows before the accounting run exists. If one is accidentally run, leave unrelated guardian/system rows alone, insert the current run's complete KPI set explicitly, and verify exactly one row per required key for the linked run. Cron session-usage synchronization can land while the optimizer is running, so preserve the exact output and exit code from the final canonical `--no-record` probe used for the plan-only decision; never mix its token count with an earlier bare-probe value.
- Update `agent_tasks` using the actual live schema. This DB uses columns such as `summary`, `payload`, `verification_result`, `commit_hash`, and `metadata`; do not assume `result_payload` exists.
- Avoid `git add .`; stage only reviewed files. In a dirty Hermes repository, verify `git diff --cached --name-status` before every commit.
- Secret-scan staged diffs before committing.
- Do not commit temp scripts with DSNs/API keys/PINs.
- A build/fix request is not complete while an independent review, required test, commit, push, task-board update, or live verification is still pending. Do not send a “completed” final report that lists one of those as a remaining gate; finish it or state a blocker without claiming completion.
- If the staged diff changes after independent review, restage and request a fresh review of the final staged snapshot before committing.
- Live DB state changes and source-control delivery are separate verification targets: confirm both, then report the exact commit/push result and current paper-only recommendation state.

## Repository hygiene and obsolescence audits

When auditing tracked Wolfy Python files for deletion, do not infer disuse from imports alone. Cross-check live cron jobs, stable global/profile wrappers, wrapper-managed duplicates, tests, allowlists, and git history/blame. Treat dirty-tree deletions as pre-existing evidence rather than authorization, and report only candidates supported by converging runtime and historical evidence.

For preservation audits of a live Hermes/Wolfy repository, snapshot staged/unstaged/untracked state at both the start and end because cron, curator, autorepair, or another worker may mutate the index during review. Classify monolithic cron state field-by-field: preserve job definitions and intentional policy, but exclude counters, last/next-run timestamps, error history, and public routing identity. Treat `.usage.json` and generated skill prompt snapshots as runtime telemetry; treat `.bundled_manifest` and `.hub/lock.json` as reproducibility state when they match the skill tree. A textual column rename inside `CREATE TABLE IF NOT EXISTS` is not a migration—cross-check clean bootstrap, populated-schema ALTERs, views, writers, compatibility scripts, and both old/new names. Also trace temporary-fixture tests through count/freshness helpers so a nominal SQLite test cannot silently read the live Postgres DSN.

For recovery-grade architecture documentation spanning `/root/.hermes` and isolated worktrees, keep tracked source, live deployed source, runtime database/scheduler state, historical evidence, and off-Git artifacts as separate evidence layers. Verify branch containment, actual live file presence, Postgres relations and rows, scheduler activation, release artifacts, rollback behavior, and auxiliary-service deployment independently. Run the canonical Wolfy suite from the `wolfy/` project directory because repository-root pytest can collect duplicate profile skill tests. Passing tests do not replace a required independent review; an interrupted or rate-limited reviewer leaves the release unapproved.

See `references/tracked-python-obsolescence-audit.md` for the deletion evidence hierarchy, `references/tracked-live-repo-preservation-audit.md` for source/config-versus-runtime classification, security checks, SQL migration review, non-mutating verification, and reporting format, and `references/recovery-grade-architecture-mapping.md` for the complete recovery audit sequence, README structure, safe commands, and reporting traps.

## External technical and market-structure data research

When adding non-OHLCV signals, keep four namespaces distinct: technical, market structure, macro risk regime, and fundamentals. Prefer official sources, but do not equate public access with an open-data license. Before implementation, verify the live endpoint, actual first/last observation, freshness, definition changes, redistribution terms, and the timestamp at which each value became available.

For lagged releases such as short interest, fails-to-deliver, COT, and revised macro series, backtests must join on `available_at <= decision_timestamp`, not merely the observation or settlement date. Never equate FINRA short-sale transaction volume with outstanding short interest, and never describe FINRA-only TRF/ADF/ORF volume as consolidated whole-market short volume. Calculate breadth from a point-in-time universe to avoid survivorship bias.

See `references/official-technical-market-structure-data-sources.md` for the researched Cboe, FINRA, Nasdaq, Treasury/Federal Reserve/FRED, SEC, CFTC, breadth, cadence, history, licensing, and ingestion guidance.

## References

- `references/dedicated-postgres-test-harness.md` — exact-DSN safety, strict TDD slices, bounded peer-auth provisioning, extension setup, clean-schema ordering, rollback fixtures, migration checks, and production-state verification.
- `references/full-suite-governance-leak-isolation.md` — diagnose focused-green/full-suite-dirty test isolation, identify shared committing writers by complete-row hashes, recover exact backed state, and block partial fixes safely.
- `references/budget-gated-optimizer-plan-only-closure.md` — durable task/run/KPI/ledger closure when the deterministic budget gate blocks implementation, including DoD and CLI/SQL pitfalls.
- `references/immutable-gate-fail-closed-validation.md` — canonical immutable-gate parsing, monthly fail-closed selection, malformed-metadata handling, regression matrix, and exact-snapshot review discipline.
- `references/paper-recommendation-logging-2026-08.md` — session-derived implementation notes for approved recommendation writer and paper-trade logger.
- `references/tracked-python-obsolescence-audit.md` — procedure for high-confidence tracked-script deletion audits across imports, cron, wrappers, duplicate copies, and git history.
- `references/official-technical-market-structure-data-sources.md` — official low-cost non-OHLCV signal sources, classification, licensing caveats, and point-in-time ingestion rules.
- `references/recommendation-pipeline-readiness-and-delivery.md` — end-to-end recommendation readiness audit, delayed-data semantics, revalidation/auto-reactivation rules, universe coverage, scheduled writer/logger wiring, and Discord delivery policy.
- `references/delayed-eod-weekend-catchup-and-immediate-recommendation-rerun.md` — weekend/T+1 catch-up probe, bounded shard ingest, interpreter fallback, exact-date verification, and immediate deterministic paper-lifecycle rerun.
- `references/live-status-snapshot-audit.md` — grounded “where are we at?” snapshot sequence, live-schema/date-fixture pitfalls, coverage interpretation, and concise decision language.
- `references/daily-multi-setup-evaluator-planning.md` — expand daily opportunity safely through T+1 catch-up, staged broad universes, near-miss attribution, orthogonal setups, point-in-time data, exact options decisions, allocator controls, and explicit user trade-offs.
- `references/mid-small-cap-multi-strategy-pivot-planning.md` — reconcile an accepted architecture with a stock-only mid/small-cap pivot, close options/concurrency/provenance blockers first, deliver a thin shadow vertical slice, and measure explicitly accepted ruin risk.
- `references/point-in-time-security-eligibility-gate.md` — audit and implement append-only, source-backed U.S./liquidity/security-risk identity with effective dates, availability cutoffs, canonical exclusions, migration safety, and focused RED coverage.
- `references/accepted-plan-autonomous-execution.md` — execute an accepted multi-phase plan through a clean worktree, durable task ledger, per-task TDD/review checkpoints, disconnection recovery, and serialized release/canary verification.
- `references/auditable-postgres-ledger-release-gates.md` — authoritative ledger state machines, immutable publication evidence, canonical reasons, direct-SQL/concurrency probes, atomic populated-schema upgrades, and subagent timeout/revision handling.
