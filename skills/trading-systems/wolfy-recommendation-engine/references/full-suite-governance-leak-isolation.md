# Full-suite governance leak isolation and safe recovery

Use this when a focused Wolfy Postgres isolation patch passes but the complete suite still changes `strategies`, `backtests`, `research_log`, or related governance state.

## Core lesson

A rollback boundary in the obvious revalidation test file is not sufficient when other integration tests call shared writers such as `seed_default_strategies()` from committing `with psycopg.connect(...)` contexts. A suite can also have unrelated schema-contract failures that prevent the required zero-regression gate. Do not commit a partial isolation patch just because the focused file is green.

## Bounded diagnosis

1. Before the first mutating test, take a restorable data-only backup of the complete governance write graph.
2. Hash complete rows with stable ordering, for example `jsonb_agg(to_jsonb(row) ORDER BY id)`, for `strategies`, `backtests`, and `research_log`.
3. Add a red-capable guard for the intended isolation property, then prove the focused module goes RED → GREEN.
4. Run the full suite under fail-fast shell semantics. Always capture post-run hashes even when pytest exits nonzero; a shell `set -e` can otherwise skip the state audit.
5. If a hash changes, compare the backed-up and live complete rows to identify exact columns—not only status or metadata pointers.
6. Bisect by test file: restore the exact baseline, run one suspect file, compare hashes, and repeat. Shared seeders in otherwise unrelated options/recommendation tests are common commit sinks.
7. Treat independent full-suite failures (for example a writer omitting a live `NOT NULL` provenance column) as separate blockers. Do not bundle their repair into the isolation task merely to make the suite green.

## Recovery

- Back up the post-failure state before restoring anything.
- Restore only the proven changed rows/columns from the pre-test backup inside one transaction.
- Verify all complete-table hashes and row counts exactly match the baseline.
- Preserve known pre-existing future fixtures; a broad `ZZ%` or future-date cleanup can destroy prior audit evidence.
- Revert the partial source edit when the task's full DoD is unmet, block the task with exact evidence, record the failed run/KPIs, and create no commit.

## Architectural next step

When multiple files commit through shared helpers, stop adding file-local rollback wrappers. Migrate to the dedicated `wolfy_test` session harness with an autouse DSN redirect and source-import isolation. Reconcile any live-schema contract failures first, then require two complete suites with byte-equivalent governance snapshots before closing the original task.
