# Green Suite, Production Mutation: Detection and Recovery

## Failure pattern

A test suite can exit 0 while changing production state when tests connect to the live database, mutate durable governance rows, and rely on cleanup or “restore” helpers that no longer restore anything. This is especially dangerous for authorization-like fields such as strategy status: a green suite can silently turn a candidate into an approved strategy.

## Release gate

1. Before any targeted test, capture a deterministic production snapshot containing:
   - exact database identity and read-only transaction state;
   - named governance-row IDs, statuses, verdicts, and approval metadata;
   - protected table counts and fixture-identity counts.
2. Compare that snapshot immediately after each test phase: regression, focused suite, and full suite.
3. Do not stage or commit until the final comparison is exactly equal. Pytest exit code and cleanup assertions are necessary but not sufficient.
4. Inspect restoration helpers as real code. A helper that is intentionally or accidentally a no-op invalidates every test that temporarily mutates production rows.

## Incident response

If a protected value changes:

1. Stop feature work and classify the DoD as failed, even if all tests passed.
2. Preserve before/after evidence and identify the exact mutating test path.
3. Follow the governing authorization policy. If restoration is allowed:
   - create a restorable database backup first;
   - restore only the proven delta with a narrow predicate;
   - re-query the complete baseline, not only an aggregate count;
   - secure the backup appropriately.
4. If implementation was committed prematurely, create a narrow revert rather than resetting a dirty shared worktree. Verify the implementation commit plus revert have zero net diff.
5. Block the feature task/run and create separate high-priority remediation work for dedicated-test-database or always-rollback isolation.
6. Retry the feature only after focused and repeated full suites prove production snapshots unchanged.

## Strategy-governance nuance

A test-created `approved` status is an invariant violation even if the test later intended to restore it. Tests must never exercise approval transitions against production. Use a dedicated test database with exact DSN validation, and assert the production approved set is byte-for-byte unchanged before and after the suite.

## Common sequencing mistake

Do not interpret “focused tests pass” as permission to commit and defer the production invariant comparison until later. The invariant comparison is part of verification and must precede any “DoD met” commit.
