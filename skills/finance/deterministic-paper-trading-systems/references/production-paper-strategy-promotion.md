# Production Promotion of a Deterministic Paper Strategy

Use this procedure when moving an approved deterministic strategy from a development/shadow branch into a production **paper-only** publisher. The goal is not merely to merge code; it is to prove schema safety, exact-snapshot authorization, bounded publication, one-publisher ownership, and reversible activation.

## 1. Separate build completion from deployment

Report these states independently:

1. implementation complete;
2. merged release snapshot complete;
3. migrations rehearsed;
4. production schema migrated;
5. source universe ready;
6. paper canary passed;
7. scheduled publisher enabled.

A branch with passing tests is not production. A release gate whose executable command remains test-database/shadow-only is not production. A hard-disabled canary flag must not be flipped unless the real publisher, invariant reader, durable artifact, and rollback callbacks exist.

## 2. Use a clean release worktree

If the live repository has unrelated modifications, never merge or stage into it. Create a clean release worktree from the current production commit, merge the strategy branch there, and resolve only true conflicts. Keep the live tree untouched until activation.

When tests conflict, preserve the safer database-isolation path. After resolution, scan the entire merged test tree for:

- literal production DSNs;
- imported default DSNs;
- subprocess arguments;
- environment fallbacks;
- schema helpers that commit DDL;
- telemetry or ancillary writers.

A global test fixture that points defaults at a test database does not protect tests containing hard-coded production DSNs.

## 3. Capture production evidence before tests

Capture production state before any test command. Record both:

- protected content counts/hashes for strategy, recommendation, paper-trade, and outcome tables;
- detailed schema inventory: columns, indexes, constraints, and triggers.

A single schema hash is useful for detection but insufficient for attribution. Preserve the underlying inventory so a delta can be explained.

Re-query after focused tests and after the full suite. If rows or schema change unexpectedly, stop promotion and identify the writer. Do not treat unchanged protected row counts as proof of safety when schema metadata changed.

## 4. Close the migration dependency graph

Do not assume the declared migration list is complete. For every migration, enumerate referenced tables, functions, indexes, and constraints and verify that an earlier migration or existing production object supplies each dependency.

Common omission pattern:

- canonical initialization SQL contains a base ledger;
- later migrations reference that ledger;
- the release migration tuple includes only the later migrations;
- clean test bootstrap hides the missing production dependency.

Create an explicit idempotent migration for missing base objects rather than applying an entire canonical bootstrap to production. Include every feature migration, including candidate/intermediate tables, in the pinned ordered migration tuple and SHA-256 list.

## 5. Rehearse three ways

Before production DDL:

1. Apply the pinned ordered migrations twice to the dedicated test database.
2. Apply them twice to a disposable clone of current production, including populated legacy rows.
3. Run focused migration/release tests and the complete suite.

If the application role cannot create a clone, use the local database administrator only to create the disposable database and assign it to the normal application owner; execute migrations as the normal application role. Do not broaden the application role's production privileges.

Verify expected tables, indexes, constraints, and triggers after both passes. Migration success on a clean test database does not prove populated-upgrade safety.

## 6. Bind approval to an exact immutable snapshot

The release artifact must include at least:

- code snapshot fingerprint;
- release configuration version;
- ordered migration hashes;
- approved strategy IDs/versions;
- paper-only/no-live-execution assertions;
- canary maximum new recommendations;
- rollback command/target;
- test, replay, and independent-review evidence hashes.

Any code, migration, config, staged-diff, or artifact edit invalidates prior review and requires regeneration. Never synthesize approval evidence merely to satisfy a type or gate.

## 7. Build a source-backed universe without per-symbol bottlenecks

For a broad U.S. stock universe, prefer official bulk feeds where possible. A practical evidence split is:

- a bulk exchange/reference feed for symbol, active status, security type, locale, currency, and primary exchange;
- an official bulk issuer/screener feed for issuer country, market capitalization, and sector;
- the canonical adjusted EOD database for signal-date close and 20-session dollar volume.

This avoids thousands of individually rate-limited detail calls. Preserve source URL, retrieval time, payload/page hashes, provider fields, and exact-symbol joins. Do not infer issuer country from ticker or company name. Missing, ambiguous, stale, or mismatched identity evidence must exclude the symbol.

Apply the policy from point-in-time evidence: U.S. common stock, approved U.S. exchange, active, USD, market cap bounds, minimum price, minimum 20-session dollar volume, benchmark-only exclusions, denylist, and known manipulation/government vetoes. Unknown sector may be retained only if policy allows it and must share one explicit `Unknown` sector bucket for cap enforcement.

## 8. Canary before scheduler

The production canary must use the real production database and real source-backed universe, but remain bounded and paper-only. It must:

- publish only explicitly approved sleeves;
- reject research-only sleeves at the writer boundary;
- enforce global concurrent-position, sector, per-position risk, and aggregate-risk limits from durable rows;
- use exact fresh option-chain provenance or an explicit configured stock fallback;
- produce zero broker orders and zero external delivery;
- rerun idempotently and return the same durable recommendation IDs;
- read back every invariant after commit.

A zero-recommendation canary is valid only when the complete pipeline ran and deterministically found no qualifying setup. An incomplete universe or missing ledger is a blocked canary, not a clean no-trade.

## 9. Transfer one-publisher ownership

Inventory current cron jobs before activation and identify the exact existing publisher. Do not enable the replacement until the canary passes for the same snapshot.

Safe handoff:

1. record old job ID, schedule, script, and enabled state;
2. pause the old publisher;
3. create or enable the new exact-snapshot publisher;
4. list jobs and prove exactly one enabled cap-consuming publisher;
5. run the new job once and verify local, paper-only output;
6. retain the old job definition as rollback target.

Downstream summaries/reviewers are not necessarily publishers; classify by actual database writes, not job names.

## 10. Non-destructive rollback

Rollback must disable the new publisher/config and restore the previous publisher/universe. It must never delete recommendations, paper trades, outcomes, source observations, migration history, or audit rows.

Dry-run rollback should prove the command recognizes the exact release scope without changing state. On canary failure, execute rollback and verify:

- pivot publisher disabled;
- previous publisher restored;
- previous universe restored;
- zero rows deleted;
- audit evidence retained.

## 11. Make baseline checks migration-aware

Define the expected production delta before applying DDL. A blanket before/after table-content hash will report a mismatch when an approved migration intentionally adds and backfills a column in an existing protected table. Use two independent checks:

1. Compare a canonical projection of every **pre-existing column** before and after; row identities and old values must be identical.
2. Validate each added/backfilled column against the migration’s explicit invariant (for example, every historical underlying outcome receives one declared `outcome_type`).

Do not treat raw `pg_dump` file hashes as canonical content hashes without normalization. PostgreSQL dumps can contain a randomized `\\restrict`/`\\unrestrict` guard token on each invocation. Strip or canonicalize those tokens, or hash ordered query results instead. Preserve a human-readable diff so an expected schema/backfill change can be distinguished from an unauthorized mutation.

Production schema migration may be staged while the publisher remains disabled when migrations have passed exact-hash review, repeated test-DB application, populated-clone rehearsal, backup, and expected-delta validation. Do not conflate “schema installed” with “strategy activated.”

## 12. Separate release authorization from daily data identity

A static production release artifact should bind immutable code and policy:

- commit/staged-patch fingerprint;
- configuration and strategy versions;
- migration hashes;
- approved sleeves and safety invariants;
- publisher identity and rollback target.

A recurring daily publisher must not remain bound to the canary’s single `signal_dt` and universe snapshot forever. Each scheduled decision run must deterministically create or select a fresh source-backed universe snapshot, persist its fingerprint and observations, create the matching evaluation run, and bind every candidate/recommendation to that run. The static release artifact authorizes **how** this occurs; the per-session run ledger proves **which data** was used.

The canary may bind one exact data snapshot for reproducibility. Scheduled authorization should then require both the immutable release artifact and a newly completed per-session readiness/evaluation ledger. Never let a scheduler replay a fixed historical snapshot merely because the canary evidence still hashes correctly.

## 13. Accept evidenced no-trades; reject missing pipelines

Do not require at least one candidate as proof that the canary worked. A valid deterministic no-trade has:

- a complete source-backed eligible-universe snapshot;
- durable terminal gate evaluations for the expected population;
- explicit passed/failed counts and reason distribution;
- a completed run state;
- zero candidates because no setup passed;
- an idempotent rerun with the same run/snapshot identity;
- zero broker orders and external deliveries.

By contrast, zero candidates with no daily run, no universe members, missing gates, stale inputs, or an unfinished stage is `pipeline_incomplete`, not `no_trade`. Production adapters should validate completeness separately from candidate count.

## 14. Verify delegated release code as untrusted work product

A timed-out or interrupted coding agent may leave syntactically partial files without a final summary. Before using delegated release work:

1. inspect `git status`, new files, and the full diff;
2. import/compile every new module;
3. run the focused tests and capture RED/GREEN explicitly;
4. verify the CLI was actually wired, not merely tested through callbacks;
5. confirm the production database and scheduler were not touched;
6. request a fresh exact-snapshot review after any repair.

Never infer success from a background task having made files or consumed its time budget.

## 15. Serialize implementation agents on one release worktree

Treat delegated coding output as untrusted shared-state work, especially when agents receive the same absolute worktree path. Do not run multiple implementation agents concurrently against one release tree: they can overwrite files, invalidate each other's reads, or leave a moving diff after timeout. Use this discipline:

1. allow at most one writer/implementation agent per worktree;
2. keep independent reviewers read-only and bind them to a commit or frozen patch rather than a mutable tree;
3. after timeout or cancellation, assume files may still have changed and refresh `git status`, full diffs, module imports, and focused tests before editing;
4. re-read exact file sections immediately before patching—never apply a repair against stale paginated reads;
5. capture the intended RED result, then repair to GREEN, run the full suite, commit, and dispatch a new review for that exact commit;
6. never interpret a timeout, completion notice, or created file as evidence that the delegated deliverable is complete.

When a long task may exceed an agent timeout, split it into sequential bounded slices: artifact/authorization contract, source-universe bootstrap, production canary, scheduler handoff, and rollback. Each slice should end at a compilable, tested commit so interruption cannot strand a half-module in the release candidate.

## Release checklist

- [ ] Clean release worktree based on current production commit
- [ ] Full merged suite passes
- [ ] Production rows and detailed schema unchanged by tests
- [ ] Migration dependency graph complete
- [ ] Ordered migration hashes pinned
- [ ] Migrations pass twice on test DB
- [ ] Migrations pass twice on populated production clone
- [ ] Exact-snapshot independent reviews approve
- [ ] Source-backed universe complete and fail-closed
- [ ] Real bounded canary passes and reruns idempotently
- [ ] Zero broker orders and external deliveries
- [ ] One enabled publisher after handoff
- [ ] Non-destructive rollback verified
