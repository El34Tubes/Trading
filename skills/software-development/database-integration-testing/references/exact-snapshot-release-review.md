# Exact-Snapshot Release Review for a PostgreSQL Test Harness

Use this recipe for a final, combined, blocking-only review of a committed database-isolation task. It complements the main workflow by proving the exact Git snapshot, import timing, concurrency, cleanup, and production immutability in one release gate.

## 1. Pin and preserve the snapshot

Record `git rev-parse HEAD`, require an empty `git status --porcelain=v1`, and compare the reviewed range against the accepted plan/base commit. Re-run the clean-tree and exact-HEAD assertions after every verification command. A passing test run on a modified tree is not evidence for the requested snapshot.

## 2. Capture a deterministic production invariant

Connect with database-enforced read-only mode, assert `transaction_read_only=on` and the exact production database name, then capture:

- required table counts;
- approved-row counts;
- the complete named governance row, including status, verdict, full metadata, and authorization fields.

Serialize with sorted JSON keys and stable separators, then compute SHA-256. Retain both the readable values and checksum. Repeat after focused tests, the full suite, schema probes, and concurrency probes. Require literal equality and checksum equality.

## 3. Prove pre-collection redirection

A fixture is too late when modules cache DSNs at import time. Add a test that imports every schema/persistence module with a module-level DSN and asserts each cached value resolves to the dedicated test database. Run this under the real pytest session so `pytest_configure` ordering is exercised rather than simulated.

Also invoke `pytest.main()` in-process with a sentinel caller DSN and assert `pytest_unconfigure` restores the exact sentinel after the run. This catches cleanup behavior that a child-process test cannot observe.

## 4. Audit ambient libpq coverage against the installed driver

Do not rely only on a hand-maintained environment-variable list. Query the installed libpq/psycopg connection-option metadata (for example, `psycopg.pq.Conninfo.get_defaults()`), extract every non-empty `envvar`, and compare it with the harness rejection set. Require no driver-known variables to be missing; legacy compatibility entries may remain as extras.

This is a release probe, not a reason to delete compatibility guards when the local libpq version does not expose them.

## 5. Exercise concurrency and schema idempotency

Launch several independent processes that call the provisioning entry point concurrently. Require every process to exit successfully and return the same validated dedicated DSN. This exercises database-creation races and the schema advisory lock.

Apply the repository schema twice to the dedicated test database with the SQL client's stop-on-error option enabled. Provisioning tests alone are useful, but the direct SQL-client probe makes hidden statement failures visible.

## 6. Verify cleanup by identity

After the full suite, query the dedicated test database in read-only mode for the collision-resistant fixture patterns used by committed-write tests. Check at least strategies, recommendations, scanner results/runs, and any other helper that commits internally. Require zero residue for the generated identities.

Use precise identity predicates (fixture namespace/token plus distinguishing fields), not broad deletion or broad assertions that could include legitimate test-database seed rows.

## 7. Combined blocking-only gate

A release PASS requires all of the following:

- exact requested HEAD and clean worktree before and after review;
- focused harness tests pass;
- full relevant suite passes serially;
- changed-file lint, compile, and diff/whitespace checks pass;
- all cached DSNs resolve to the dedicated test database;
- installed-libpq environment audit has no missing variables;
- concurrent provisioning succeeds;
- schema applies twice with stop-on-error;
- generated committed-write fixture residue is zero;
- production readable invariant and checksum are identical before/after.

Report one final PASS/FAIL verdict. List only release blockers as findings; keep successful evidence compact but concrete. Do not edit the reviewed snapshot during a final review unless the user explicitly changes the task from review to repair.