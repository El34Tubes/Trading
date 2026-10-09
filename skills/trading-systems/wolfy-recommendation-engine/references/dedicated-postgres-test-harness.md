# Dedicated Postgres integration-test harness

Use this pattern when migrating Wolfy integration tests away from the live `wolfy` database.

## Safety contract

- Read test connectivity only from `WOLFY_TEST_POSTGRES_DSN`, with a default that targets `wolfy_test`.
- Parse the DSN with `psycopg.conninfo.conninfo_to_dict`; do not validate by substring matching.
- Require the parsed database name to equal `wolfy_test` exactly. Reject `wolfy`, `wolfy_prod`, `wolfy-production`, and every other database name.
- Re-check `SELECT current_database()` after connecting and immediately before schema application.
- Provision only the exact, constant identifier `wolfy_test`; never interpolate an environment-provided database name into `CREATE DATABASE`.
- Capture approved-strategy identity/governance metadata and relevant production row counts before the suite, then query the same snapshot after it. Equality is a release gate.

## Strict TDD slices

1. RED: set `WOLFY_TEST_POSTGRES_DSN` to the live DSN and assert resolution raises a dedicated-test-database error.
2. GREEN: implement only exact parsed-name validation.
3. RED: test collision-resistant names and dates outside production history.
4. GREEN: add a `FutureFixture` helper with a `ZZ...` ticker, `unit_...` strategy name, and year >= 2100.
5. RED: provision twice, insert through the test connection, close it, and verify the row does not exist from a fresh connection.
6. GREEN: add idempotent provisioning/schema application and a context manager that always explicitly rolls back.
7. Migrate one integration test file at a time, run that file, then continue. Finish with all migrated files and the full isolated suite.

## Provisioning and schema application

- Connect to an administrative database such as `postgres` to test/create `wolfy_test`.
- Prefer the configured role when it has `CREATEDB` and extension privileges.
- On a local Linux host where Hermes is running as OS root and the DSN uses `/var/run/postgresql` with no password, a bounded `runuser -u postgres -- createdb --owner=<test-role> wolfy_test` fallback is acceptable. Keep command arguments fixed and use `subprocess.run(..., shell=False, check=True)`.
- Install required extensions only in `wolfy_test`. For privileged extensions such as `vector`, use the same bounded local peer-auth pattern and an exact `--dbname=wolfy_test`.
- Serialize schema setup with a Postgres advisory lock so parallel pytest workers cannot race migrations.
- Apply the foundational EOD migration first, then operational-table bootstrap, then `postgres_init.sql`, followed by component-specific ensure functions and later migrations.
- Run schema application twice in the harness test. Clean-database ordering defects hidden by the mature live database are real migration bugs and should be fixed in the canonical SQL, not papered over only in tests.

## Clean-schema ordering pitfalls

A mature database can hide forward references in an allegedly idempotent SQL file. Before relying on `postgres_init.sql` for a fresh test DB:

- Add columns before any `UPDATE`, trigger, or payload expression references them. In particular, provenance fields such as `agent_tasks.source_table` and `agent_tasks.source_id` must precede payload refreshes.
- Create canonical relations before `ALTER TABLE` compatibility blocks. `universe_backfill_targets` must exist before adding alias columns/triggers.
- Add `universe_symbols` compatibility columns before creating the `universe` view that selects them.
- Preserve `IF NOT EXISTS` and non-destructive live-upgrade behavior while making clean bootstrap work.

## Rollback fixture rules

Do not write the fixture as `with psycopg.connect(dsn) as conn:`: psycopg's connection context commits on successful exit. Instead:

```python
@contextmanager
def test_connection():
    conn = psycopg.connect(provision_test_database())
    try:
        assert conn.execute("select current_database()").fetchone()[0] == "wolfy_test"
        yield conn
    finally:
        conn.rollback()
        conn.close()
```

Provision/upgrade outside the per-test transaction. Production test code can then call normal functions, while fixture DML is discarded even after successful assertions. Existing explicit cleanup may remain temporarily during migration, but rollback is the actual isolation boundary.

If an application helper commits internally, call it only during schema provisioning or refactor it before relying on rollback isolation. A commit inside the test transaction defeats the harness.

## Hidden secondary-write sinks

Literal-DSN migration is necessary but not sufficient. Some tests appear local because they assert against temporary SQLite, yet production helpers may also perform Postgres-first or dual-write persistence through a default connection factory.

Use this containment pattern:

1. Add a session-scoped autouse pytest fixture that provisions `wolfy_test` and overrides `WOLFY_POSTGRES_DSN` for the entire test process.
2. Restore the prior environment value after the session. Pure configuration tests may temporarily delete/override it with `monkeypatch`, but state-mutating tests must never regain the live default.
3. Search test call graphs for `connect_postgres`, recommendation/scanner loggers, compatibility writers, and other helpers that open their own connections; do not stop after searching for `psycopg.connect` or `dbname=wolfy` literals.
4. Write an end-to-end regression that calls a real implicit dual-write helper, verifies the resulting Postgres row exists only in `wolfy_test`, and proves the live table count is unchanged.
5. For helpers that commit internally, use unique fixture markers and deterministic cleanup in `wolfy_test`; an outer rollback cannot undo a separate committed connection.

A production-count increase during a suite is a **revision gate**, not permission to delete data. Query the new rows' IDs, timestamps, statuses, tickers, and provenance. If they match test fixtures, expand the isolation boundary, preserve the rows for audit unless separately authorized, set the current observed count as the next before/after baseline, and rerun serially. If they came from concurrent legitimate automation, record that provenance and use a fingerprinted baseline (approved strategy metadata plus max IDs/timestamps and scoped counts) rather than blindly requiring a global count to remain static.

## Worktree source-import isolation

Database isolation is not enough when a clean worktree coexists with `/root/.hermes/wolfy`. Legacy wrappers may prepend that production source directory to `sys.path`, causing later tests to exercise production modules while writing to `wolfy_test`. A focused test can pass while the serial suite imports a stale production `orchestration_runner` from `sys.modules`.

Enforce source origin at pytest session and test boundaries:

1. Resolve the current worktree's `wolfy/` directory from `conftest.py`, place it first on `sys.path`, and remove a distinct production `/root/.hermes/wolfy` entry.
2. Detect cached Wolfy modules whose `__file__` is outside the worktree. Evict/re-import only the known project modules, or fail closed if safe reloading is ambiguous.
3. Reassert both source-path and `WOLFY_POSTGRES_DSN=wolfy_test` isolation before tests that can import legacy wrappers.
4. Add a regression that deliberately pollutes `sys.path` and `sys.modules`, then proves `orchestration_runner`, readiness modules, and modules with cached `DEFAULT_DSN` constants resolve inside the worktree and target `wolfy_test`.
5. Run the complete `wolfy` suite serially; a focused suite does not expose order-dependent module-cache contamination.

Reading production files explicitly by `Path` may remain valid for audit tests; source-import isolation should block imports, not read-only path inspection.

## Migration checklist

- Import the shared `test_connection` helper at module scope.
- Replace every hard-coded `dbname=wolfy` connection, including direct literals and local `dsn` variables.
- Search the final migrated files for `dbname=wolfy`, `WOLFY_POSTGRES_DSN`, and direct `psycopg.connect(...)` calls.
- Remove now-unused `psycopg` assignments/imports, but keep `pytest.importorskip("psycopg")` where optional dependency behavior is intentional.
- Give the context manager an accurate psycopg connection return type so static analysis recognizes `.execute()`.
- Mark helper functions beginning with `test_` as non-tests or prefer a non-collectable name such as `postgres_test_connection`.
- Run focused harness tests, each migrated integration file, the combined set, and the full isolated suite.
- Run a staged secret scan and verify production snapshots are byte-for-byte/value-for-value unchanged before committing.
