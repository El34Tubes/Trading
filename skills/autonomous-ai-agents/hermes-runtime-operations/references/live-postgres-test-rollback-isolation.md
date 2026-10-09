# Rollback-Only Integration Tests Against a Live Postgres Schema

Use this only when a disposable test database is not yet available and a test must exercise the production schema. A dedicated test database remains the preferred long-term design.

## Failure mode

A test suite can pass while silently mutating governance or operational rows. In psycopg, `with psycopg.connect(dsn) as conn:` commits on normal context-manager exit. A no-op “restore” helper does not protect production state, and cleanup limited to synthetic tickers will not restore shared rows such as strategy statuses.

## Safe bounded repair

Wrap each test connection in an outer transaction that is always rolled back:

```python
from contextlib import contextmanager

@contextmanager
def rollback_connection(psycopg, dsn: str):
    conn = psycopg.connect(dsn)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
```

Use `with rollback_connection(psycopg, dsn) as conn:` for every live-schema integration test. The tested code may read and mutate rows inside that transaction, but no test-owned state should commit or become visible to other sessions.

### Preconditions

- Confirm the code under test does not call `commit()` or open a separate writer connection. An outer rollback cannot undo those writes.
- Keep synthetic fixtures namespaced and future-dated where applicable, but treat that as defense in depth—not the primary isolation mechanism.
- Never use a helper that resets governance rows to guessed defaults; snapshot/rollback preserves the actual production state.

## Verification

1. Inventory the complete write graph before testing. Do not assume the table named in the test is the only mutation surface: strategy revalidation may write `backtests` and `research_log`, then update a pointer or gate object in `strategies.metadata`.
2. Because this is a live database, take a restorable data-only backup of every table in that write graph **before the first verification run**. A passing suite is not proof that cleanup/rollback worked, and discovering leakage after the run is too late to reconstruct arbitrary pre-test JSON exactly.
3. Capture byte-comparable snapshots of complete safety-critical rows, not a convenient subset. Hashing `jsonb_agg(to_jsonb(row) ORDER BY stable_primary_key)` catches metadata/pointer drift that a projection of `id,name,status,params,notes` misses. Snapshot dependent artifact tables too, using stable filters or complete-table hashes/counts as appropriate.
4. Run the focused suite and compare all snapshots before/after.
5. Run the full project suite and compare all snapshots again. Then run the full suite a second time: monotonically advancing IDs, pointers, timestamps, or row counts expose committed side writers even when each test's primary connection rolls back.
6. Query for leftover synthetic fixture rows across every table the flow writes.
7. Verify the committed artifact, not only the dirty worktree: create a detached temporary worktree at `HEAD`, run the same state-preservation checks there, then remove the worktree.

A passing test count alone is insufficient. The completion evidence should include focused/full counts, unchanged hashes for every governance table in the write graph, zero leaked fixtures, and the exact commit hash. If the suite passes but any hash/count changes, the isolation task has failed and must not remain completed.

## Partial isolation and recovery

Wrapping one test module's connection is only a partial fix if another test or code path commits through its own connection. A common signature is: focused tests preserve `strategies`, while the full suite repeatedly appends one artifact row and advances a strategy metadata pointer. Treat this as a reproducible production-state regression, not harmless test output.

When leakage is discovered:

1. Stop further test runs.
2. Back up affected parent and dependent tables before deleting anything, even if the rows appear obviously synthetic.
3. Identify rows from exact IDs/timestamps/test provenance and restore only the proven delta; never reset a whole governance table to defaults.
4. Respect foreign-key order during recovery: remove dependent rows first (for example `research_log`), then parent artifacts (`backtests`), then restore the governance pointer/metadata.
5. Verify the complete governance-table hash exactly matches the pre-test hash and the leaked parent/dependent row counts are zero.
6. Reopen/block any task whose stored DoD claimed byte-equivalent state, replace stale `PASS` verification text with the fresh failure evidence, and queue a bounded corrective task.

The durable fix remains a disposable test database or rollback boundary that contains **every** writer. Recovery is not a substitute for isolation.

## Dirty repository / narrow commit

If the test file already contains unrelated uncommitted work, do not commit the entire file. Build the intended version from `git show HEAD:<path>`, apply only the isolation transformation, stage that exact blob or a minimal patch, inspect `git diff --cached --name-status` and `git diff --cached --check`, then commit. The working tree may retain unrelated edits while the commit remains narrow.

## Task-ledger closure

After verification:

- Complete the isolation prerequisite task with actual test counts and commit hash.
- Requeue only tasks whose blocker was precisely that prerequisite; clear the stale blocker text and preserve an audit link to the completed prerequisite.
- Do not mark the downstream implementation complete merely because its test-safety prerequisite is fixed.
