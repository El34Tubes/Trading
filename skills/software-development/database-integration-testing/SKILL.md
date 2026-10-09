---
name: database-integration-testing
description: "Safely test applications that use implicit database configuration, committed cross-connection writes, and production-like PostgreSQL schemas."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [testing, postgres, pytest, database-safety, integration-testing]
    related_skills: [test-driven-development, requesting-code-review, systematic-debugging]
---

# Database Integration Testing

## Overview

Build and verify integration tests without allowing test code to mutate a live database. This skill applies when application helpers choose a DSN implicitly, cache environment-derived defaults during import, open their own connections, or commit independently of the test's transaction.

**Core principle:** Redirect implicit connections before imports, validate the destination by exact database identity, and prove production invariants are unchanged.

## Triggers

Use this skill when:

- pytest tests call real PostgreSQL persistence helpers;
- production code opens internal connections that a rollback fixture cannot control;
- DSNs/defaults are read into module constants during import;
- a task requires an immutable production baseline before and after tests;
- schema bootstrap or migration SQL must work on both clean and already-provisioned databases.

## Workflow

### 1. Inventory database access

Search tests and imported helpers for:

- implicit `connect()` calls;
- default DSN constants;
- environment reads performed at module scope;
- helpers that open separate connections or commit internally;
- hardcoded production DSNs;
- subprocesses that inherit the test environment.

Classify every match as an actual write path, a mocked path, a negative configuration test, or a read-only production invariant probe.

### 2. Capture immutable production invariants

Before running any potentially writing test, capture exact values for the required tables and named records. Include all state whose preservation matters: table counts, approved-row counts, status/verdict fields, and full authorization/approval metadata rather than only a single aggregate. Compare literal values after focused tests and after the full suite.

Open production invariant connections in a database-enforced read-only mode (for example, `default_transaction_read_only=on`) and assert both `transaction_read_only` and `current_database()` before querying. For large nested metadata, serialize deterministically and compare a checksum as additional evidence; retain the readable summary too.

If any value differs, stop. Do not delete, update, or otherwise repair production rows merely to recover the baseline.

### 3. Provision a dedicated test database

- Accept only an exact dedicated database name, not merely a name that looks non-production.
- Validate the **raw DSN syntax before parsing** as well as the entire parsed target. Driver parsing canonicalizes URI and keyword forms, so a semantically local URI can become indistinguishable from an approved keyword DSN after parsing. If the safety contract is keyword-only, reject every `postgres://` / `postgresql://` form—including local-looking socket URIs—before parsing.
- Validate the **entire parsed connection target**, not only `dbname`. Fail closed on remote hostnames/IPs, TCP localhost unless explicitly authorized, passwords/passfiles, service indirection, SSL overrides, unsafe users, `hostaddr`, and unrecognized parameters. Require an exact positive control such as `dbname=<test_db> host=/var/run/postgresql user=<peer_user>` with no extras.
- Treat ambient libpq variables as connection inputs. Reject them by **presence**, not truthiness, before parsing or connecting. Cover target/user/database, password/passfile, service, options, TLS, GSS/auth, protocol, and session-selection variables; use installed libpq metadata to audit the current surface while retaining legacy compatibility entries.
- Re-run the same validator inside every directly callable side-effect path: normal and admin connection setup, schema application, database-creation fallback, and extension/privileged subprocess setup. Validation only in the public resolver leaves internal bypasses.
- Derive the admin DSN only after validation; changing only `dbname` while preserving an unsafe or environment-influenced endpoint can reach production infrastructure.
- Reject production and production-like DSNs.
- Apply schema idempotently under an advisory lock, and verify `current_database()` immediately before schema work or yielding a test connection.

### 4. Redirect before test collection—and before provisioning imports

When application modules cache environment-derived DSNs at import time, set the test DSN in `pytest_configure`, before pytest imports test modules. A session fixture alone is too late for this class of code.

Treat the provisioning call itself as an import boundary: schema setup frequently imports application modules to call `ensure_*_schema()` helpers. Use this exact order:

1. Resolve and validate the dedicated test DSN without importing schema/application modules.
2. Save the caller's original application DSN environment value.
3. Export the validated test DSN as the application's implicit/default DSN.
4. Only then provision/apply schema.
5. If provisioning fails, immediately restore the caller's environment before re-raising.
6. Restore it again during normal `pytest_unconfigure` teardown.

Do not assume `pytest_configure` is early enough merely because it precedes test collection; code executed inside `pytest_configure` can itself cause the premature imports. Audit the conftest import graph and the provisioning path.

Also use an autouse session fixture as an explicit invariant guard. Tests may temporarily delete or override the environment through `monkeypatch`; normal fixture restoration should return them to the session value.

Add a fresh-process regression that imports every schema module known to cache a DSN and parses each cached `DEFAULT_DSN` (plus any function defaults bound from it). Assert the resolved database identity is exactly the dedicated test database and explicitly not production. Run this test once before the ordering fix to capture a meaningful RED; an in-process reload after setup can mask the bug.

When tests or legacy scripts mutate `sys.path`, treat source selection as part of database isolation. A full suite can import a same-named module from a canonical/deployed checkout even though focused tests pass. Normalize the worktree source to the first path at conftest/configuration and per-test boundaries, remove known competing source entries, and inspect cached module origins. Evict only local modules cached from the known competing tree; keep correctly loaded worktree modules, and fail closed on unexpected third-party origins. Re-import required modules only after exporting the test DSN, then validate both `module.__file__` and cached DSN identities. A regression should simulate both path and `sys.modules` contamination with synthetic modules. See `references/pytest-worktree-source-isolation.md`.

### 5. Use the right isolation mechanism

- For test-owned connections: wrap work in a transaction and always roll back.
- For production helpers that open and commit their own connections: rely on dedicated-database redirection, unique fixture identities, deterministic assertions, and explicit test-database cleanup.
- Use future-dated and namespaced fixture data when collisions with realistic historical data are possible.
- Put cleanup in `finally` and delete by the unique fixture identity, not only by a returned row ID. A helper can commit and then raise before returning its ID; ID-dependent cleanup would leak the committed row.
- After cleanup, query the dedicated test database and assert the unique scanner/recommendation identities are absent. Where legacy static fixtures exist, remove them only from the verified test database and prove their count is zero.

### 6. Write a side-effect-safe RED test

A regression test for missing isolation must fail before it can invoke the dangerous write:

1. Read the implicit DSN.
2. Assert that it exists and resolves to the dedicated test database.
3. Only then call a real write helper.
4. Assert the row exists in the test database.
5. Assert the production invariant remains unchanged.

This preserves strict RED-GREEN discipline without deliberately writing to production during RED.

### 7. Verify completely

Run, serially unless parallel safety is established:

1. Capture the exact production baseline **before the first targeted test**, including named strategy statuses and approval metadata—not only table counts.
2. Run the regression test, then immediately compare production invariants.
3. Run focused database/configuration suites, then immediately compare production invariants again.
4. Run the full relevant pytest suite, then immediately compare production invariants again. A zero pytest exit is not sufficient: cleanup code can be a no-op while tests still commit production mutations.
5. Apply schema twice with stop-on-error enabled.
6. Run Ruff on changed files, exact `py_compile` on changed Python files, and whitespace/diff checks.
7. Perform a static re-audit of all implicit callers and hardcoded production DSNs.
8. Only after the final invariant comparison matches may you stage or commit implementation changes. Never make a provisional “DoD met” commit before this release gate.

If any protected production value changes, treat the run as failed even when every test passes. Preserve evidence and follow the governing recovery policy; if restoration is authorized, take a restorable database backup first, restore only the proven delta, verify exact baseline parity, and revert any prematurely committed implementation. Record the unsafe test path as separate remediation work before retrying the feature.

See `references/green-suite-production-mutation-recovery.md` for a compact incident/recovery pattern covering no-op restore helpers, premature commits, strategy-approval invariants, and task/run closure.

Repo-wide lint failures that predate the task do not invalidate a clean changed-file gate, but report both honestly.

### 8. Stage and commit safely

Stage an explicit file list, verify no unstaged changes remain, inspect the staged diff, run added-line security scans, re-check production invariants, and only then commit. Do not push unless requested.

### 9. Perform an exact-snapshot release gate

For a final combined review, pin the requested HEAD and require a clean tree before and after verification. In addition to focused/full tests, audit cached import-time DSNs under the real pytest lifecycle, compare the harness's ambient-variable rejection set with installed libpq metadata, exercise concurrent provisioning, apply schema twice with stop-on-error, query for committed-write fixture residue, and compare a deterministic production-invariant checksum before/after. Return one blocking-only PASS/FAIL verdict; do not modify the reviewed snapshot unless the user explicitly asks for repair.

For plan-spec reviews of authoritative PostgreSQL ledgers, read the complete accepted plan—not only the named task—and execute rollback-wrapped direct-SQL probes for INSERT bypasses, illegal updates, canonical enum/array violations, empty references, and post-terminal invariant invalidation. Application-level validation and a green focused suite do not prove the database fails closed. See `references/plan-spec-ledger-compliance-review.md` for the requirement matrix and adversarial probe checklist.

After specification compliance passes, run a distinct ledger release-safety quality gate: terminal-state immutability (including child rows, child reparenting via `run_id`, published-parent identity/deletion, and waiting-writer races), populated partial-schema upgrades that validate non-null legacy values rather than presence alone, atomic/concurrency-locked execution through the real deployment command, pure-date runtime validation, nonfinite JSON rejection before SQL, and timestamp chronology. A trigger added by a migration does not validate pre-existing rows. See `references/auditable-ledger-release-safety.md`.

For deterministic identities derived from canonical application JSON, make PostgreSQL an independent authority: reproduce the exact byte serialization, recompute the digest on insert, freeze the digest and every input immediately in all statuses, and reject mismatched legacy rows before backfill. Do not hash `jsonb::text` when Python `json.dumps` parity is required; whitespace, Unicode, and surrogate escaping differ. See `references/deterministic-postgres-identities.md`.

Treat immutable rerun fields outside the identity hash as a separate contract. Probe a direct SQL change from one valid canonical value to another—not only malformed values—and require rejection before an application rerun can observe drift. Also compare canonical text predicates literally across layers: PostgreSQL's default `btrim(text)` is not equivalent to Python `str.strip()`. Probe empty, space-, tab-, newline-, and carriage-return-padded logical keys in direct SQL and populated migration fixtures. See `references/canonical-ledger-identity-probes.md`.

When canonical fields live inside JSONB, test the nested document independently of scalar-column guards. A trigger that validates nested stage fields only during terminal publication still permits malformed authoritative preterminal rows, and a migration that checks only `jsonb_typeof(document) = 'object'` can preserve invalid populated metadata. Require direct SQL rejection in every lifecycle state and atomic migration failure for malformed but object-shaped legacy JSON. Treat each array invariant as independent: nonempty, canonical elements, uniqueness, and ordering each need a separate counterexample. In particular, send an unsorted-but-otherwise-valid array through the application writer, direct SQL, and a populated partial-schema migration; a green malformed-value suite can miss an absent ordering check. See `references/nested-json-ledger-canonicality.md`.

See `references/exact-snapshot-release-review.md` for the complete release-review recipe and evidence checklist.

For repeated ledger review failures, use a bounded snapshot-specific revision loop: convert every finding into adversarial RED coverage, review each new exact commit, and escalate for explicit user authorization after three failed quality revisions. A timed-out background implementer is an unknown outcome—not proof of failed work—so inspect the shared worktree and focused tests before retrying or discarding changes. See `references/bounded-ledger-review-loops.md`.

## Pitfalls

- **Setting the DSN only in a fixture:** module constants may already point at production after collection imports.
- **Provisioning before exporting the test DSN:** schema bootstrap can import application modules and cache production defaults even from inside `pytest_configure`. Resolve/validate, export, then provision.
- **Testing cached defaults only in an already-running interpreter:** module state from an earlier import or reload can make the regression pass accidentally. Verify RED/GREEN in a fresh pytest process and inspect every affected module's parsed cached DSN.
- **Fixing only `sys.path` after cross-checkout pollution:** already-imported modules remain in `sys.modules`. Normalize search paths and selectively evict known local modules whose `__file__` proves they came from the competing checkout; fail closed on unexpected origins rather than purging modules indiscriminately.
- **Reloading every local module defensively:** this can split module identity and leave dependent modules holding stale objects. Preserve modules already resolved under the authoritative worktree.
- **Assuming rollback covers internal connections:** independently committed helper writes survive the outer fixture rollback.
- **Failing RED after the write call:** the first run may mutate production. Put the database-identity assertion first.
- **Using substring safety checks:** exact database-name validation is safer than rejecting a few known production names, but database identity alone is still insufficient; validate endpoint, authentication mode, user, and all effective connection options.
- **Validating only parsed DSN parameters:** parsers erase syntax distinctions. If the contract forbids URI DSNs, reject the raw URI form before parsing—even a URI that resolves to the approved local socket/user/database.
- **Ignoring ambient libpq variables:** a keyword DSN with only `dbname`, `host`, and `user` can still be influenced by `PGPASSWORD`, `PGPASSFILE`, `PGSERVICE`, `PGSERVICEFILE`, `PGHOSTADDR`, `PGSSLMODE`, or `PGOPTIONS`. Sanitize or fail closed before provisioning and before admin access.
- **Deriving an admin DSN before validation:** replacing `dbname` while preserving an unsafe remote host can run admin queries against production infrastructure.
- **Cleaning up only by returned ID:** a helper may commit and fail before returning; clean by collision-resistant fixture identity in `finally`, then assert absence.
- **Cleaning production after tests:** this hides a safety failure and violates immutable-baseline requirements.
- **Running schema only on an existing database:** test both applicability and idempotency by applying it twice to the dedicated test database.
- **Checking only `NEW.run_id` in child immutability triggers:** an update can reparent a fact away from a published ledger. Validate both old and new parents, and separately guard published-parent updates/deletes.
- **Treating non-null legacy fields as canonical:** migration triggers apply only to future writes. Explicitly scan every populated row for cross-field invariants before finalizing constraints.
- **Assuming inline constraints are upgraded by `CREATE TABLE IF NOT EXISTS`:** on an existing partial table, inline `CHECK`/FK/uniqueness definitions are skipped. Explicitly recreate the full contract, inspect `pg_constraint`, and probe the migrated partial table with invalid direct SQL.
- **Treating a unique digest as an authoritative identity contract:** uniqueness permits arbitrary hashes and coordinated field/hash rewrites. Recompute the digest in the database on insert and freeze both digest and every source field immediately after insertion, independent of lifecycle status.
- **Hashing `jsonb::text` for cross-language parity:** PostgreSQL rendering is not byte-identical to Python compact sorted JSON, especially for whitespace and non-ASCII/surrogate escaping. Implement and test the exact canonical byte contract.
- **Validating only the most complex legacy table:** adversarially populate every affected table; parent stage arrays and manifest status/count/quality/JSON fields can remain bypassable even when gate-row migration tests are exhaustive.
- **Relying on a test-only migration lock:** exercise the real deployment command with transactional and advisory-lock guarantees; a late failure must not leave committed backfills.
- **Using fixed sleeps as concurrency proof:** synchronize on a thread/process event and, where practical, confirm the database session is actually waiting on the intended lock before releasing it.
- **Claiming Ruff passed when only targeted Ruff passed:** state the scope precisely and disclose unrelated baseline findings.

## Verification Checklist

- [ ] All implicit database callers inventoried
- [ ] Dedicated database identity and full effective endpoint/authentication policy validated exactly
- [ ] Raw URI syntax is rejected before parsing when the specification requires keyword DSNs, including semantically local socket URIs
- [ ] Keyword DSNs cover remote hosts/IPs, localhost TCP, credentials, service indirection, unsafe users, and extra options
- [ ] Ambient libpq variables are rejected by presence or explicitly sanitized before every normal/admin/schema/subprocess path
- [ ] Directly callable side-effect helpers invoke the same validator before connections or subprocesses
- [ ] Admin DSN derivation occurs only after the test target passes validation
- [ ] DSN resolved/validated and exported before provisioning or schema-helper imports
- [ ] Conftest and provisioning import graphs audited for modules that cache environment-derived defaults
- [ ] Fresh-process regression proves every affected cached DSN/default resolves exactly to the dedicated test database
- [ ] Original environment restored after normal pytest teardown and provisioning failure
- [ ] Real write-helper regression is side-effect-safe during RED
- [ ] Committed writes use unique fixtures, `finally` cleanup by identity, and post-cleanup absence assertions
- [ ] Focused and full suites pass serially
- [ ] For final reviews, exact requested HEAD and clean worktree are unchanged before/after verification
- [ ] Installed libpq connection metadata exposes no ambient environment variable missing from the harness guard
- [ ] Concurrent provisioning succeeds under the schema advisory lock
- [ ] Ledger child updates validate both old and new parent identities; published parents cannot be mutated or deleted
- [ ] Populated migration fixtures include invalid-but-non-null cross-field values across every affected table and fail closed
- [ ] Deterministic stored identities are recomputed authoritatively by PostgreSQL and match the application's exact canonical byte serialization
- [ ] Identity digest and every hashed source field are immutable immediately after insert in every lifecycle status
- [ ] Rerun-contract fields excluded from the identity hash reject direct changes between distinct valid canonical values
- [ ] Canonical text acceptance matches across application and PostgreSQL for empty, space-, tab-, newline-, and carriage-return-padded keys
- [ ] Nested JSON/JSONB canonical fields reject malformed direct SQL in preterminal as well as terminal states, and malformed populated legacy documents abort migration atomically
- [ ] Every nested array contract is probed property-by-property; an unsorted-but-valid array is rejected by the application writer, direct INSERT, direct UPDATE in every mutable lifecycle status, and populated partial-schema migration; a sorted positive control passes and persists in its original order
- [ ] Cross-language vectors cover JSON escapes, controls, BMP Unicode, and supplementary-plane surrogate pairs
- [ ] Invalid legacy identity rollback removes namespace-local helper DDL as well as table changes
- [ ] Upgraded partial tables have the full canonical constraint set; `pg_constraint` inspection and post-migration invalid direct SQL probes confirm no clean-bootstrap-only constraints were skipped
- [ ] Real deployment invocation is atomic and uses the required concurrency lock
- [ ] Committed-write fixture identity queries show zero residue after the suite
- [ ] Schema applies twice without errors
- [ ] Production invariant connection is database-enforced read-only
- [ ] Production before/after counts, governance row, and authorization metadata match exactly
- [ ] Changed files pass lint, compile, and diff checks
- [ ] Staged file list is explicit and working tree is clean after commit

## References

See `references/postgres-test-isolation.md` for the base implementation and verification recipe, including why fixture-only redirection and transaction-only isolation can fail.

See `references/fail-closed-dsn-and-cleanup.md` for complete DSN endpoint/auth validation, cleanup that survives post-commit exceptions, and read-only production checksum verification.

See `references/uri-and-ambient-libpq-bypass-closure.md` for raw URI rejection, comprehensive ambient libpq coverage, no-side-effect RED tests, and validation of directly callable connection/subprocess paths.

See `references/import-time-dsn-ordering.md` for the resolve → export → provision sequence, fresh-process cached-default regression, failure restoration, and complete verification recipe.

See `references/pytest-worktree-source-isolation.md` for deterministic reproduction and safe repair of combined `sys.path`/`sys.modules` contamination across worktrees while preserving test-database defaults.

See `references/auditable-ledger-release-safety.md` for terminal-ledger immutability, concurrent publication races, populated partial-schema upgrades, strict date/JSON/chronology validation, and the separate release-safety quality gate.

See `references/deterministic-postgres-identities.md` for exact Python/PostgreSQL canonical-hash parity, immediate identity-tuple immutability, atomic invalid-legacy rollback, and adversarial vector tests.
