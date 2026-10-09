# PostgreSQL Test Database Isolation

## Reusable harness

A safe integration-test harness should provide:

- an exact allowlisted database name such as `app_test`;
- a DSN resolver that parses both keyword and URI DSNs and rejects every other database name, including production-like variants;
- idempotent database creation through a maintenance database;
- idempotent extension and schema setup;
- an advisory lock around schema application when tests may start concurrently;
- a context-managed connection that verifies `current_database()`, yields one transaction, and unconditionally rolls back and closes in `finally`;
- collision-resistant future fixtures for tickers, strategy names, and dates.

Mark imported helpers such as `test_connection` with `__test__ = False` when pytest might collect them by name.

## Migration inventory

Do not rely only on searching for a literal production DSN. Inspect state-mutating tests for:

1. `psycopg.connect(...)` and project-specific `connect(...)` wrappers;
2. imported constants such as `DEFAULT_DSN` or `DEFAULT_PG_DSN`;
3. subprocess commands that receive `--dsn` or inherit a production DSN from the environment;
4. helper functions that commit internally;
5. ancillary metrics, audit, telemetry, and coordination writes;
6. default configuration tests that merely assert the production default and should remain unchanged.

A subprocess cannot participate in the parent's rollback transaction. If database writes are irrelevant to that subprocess test, disable or redirect that ancillary writer rather than claiming transactional isolation. If writes are part of the behavior, give the subprocess its own dedicated test database and explicit cleanup contract.

## Schema verification

Run provisioning twice, then apply the canonical schema twice against the dedicated test database with fail-fast behavior (for example, `psql -v ON_ERROR_STOP=1`). A runtime `ensure_*` function passing does not by itself prove the canonical initialization script works on a clean or upgraded database.

When a clean test database exposes missing prerequisites that production already had, fix the canonical schema additively (`IF NOT EXISTS`, prerequisite relation/column before compatibility updates). Do not seed production data into tests merely to hide schema drift.

## Fixture correctness

Tests migrated off production often accidentally depended on production rows or metadata. Seed the complete predicate under test. For an approved paper strategy this may include status plus approval scope and explicit paper-recommendation authorization, not status alone.

Prefer rollback over manual cleanup. Cleanup blocks can remain to assert idempotency or remove rows inside a test, but they are not the isolation guarantee and should not call `commit()`.

## Phased production proof

Capture and preserve raw production baseline output before any test runs. Then compare after each phase:

1. harness tests;
2. focused migrated tests;
3. all migrated integration suites;
4. full project suite;
5. schema-idempotency checks, if they could touch live state.

Use exact, deterministic queries over the protected rows and counts. Include safety-critical strategy identity/status/verdict, not only aggregate counts.

If any value changes, stop immediately. Do not stage or commit. Do not delete or rewrite the unexpected rows unless the user explicitly authorizes repair. Report before/after values and the last phase that ran. This preserves evidence and narrows investigation.

## Common pitfall

A full suite can be green while still mutating production. Test assertions usually validate behavior, not absence of unrelated side effects. Literal-DSN scans and passing tests are supporting checks; unchanged live before/after queries are the proof.
