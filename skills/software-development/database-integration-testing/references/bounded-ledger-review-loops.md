# Bounded Ledger Review Loops

Use this workflow for authoritative database-ledger changes that require repeated specification and release-safety review.

## Why

A green application test suite does not prove an authoritative database schema fails closed. Independent reviewers often uncover progressively deeper direct-SQL, migration, concurrency, and canonicalization bypasses. Revision loops need strict snapshot control and an escalation boundary so reviews remain meaningful rather than endless.

## Workflow

1. **Pin the snapshot.** Record the exact clean HEAD and cumulative task range. Reviews are valid only for that snapshot.
2. **Separate gates.** Run specification compliance first, then code-quality/release-safety review. A passing spec review does not imply migration or concurrency safety.
3. **Convert each finding into adversarial RED tests.** Prefer direct SQL, populated partial schemas, old/new foreign-key reparenting, terminal-row mutation, and valid-to-valid identity drift—not only malformed inputs.
4. **Revise narrowly.** Preserve already-passing contracts and stage only task files. Re-run focused, full, migration-twice, concurrency, static, and production-invariant checks.
5. **Review the exact new commit.** Any post-review edit invalidates the verdict.
6. **Bound revisions.** After three failed quality revisions, stop and request explicit user authorization for one additional correction/review. Never silently continue an unbounded loop or accept a known authoritative-SQL bypass.
7. **Treat timeout as unknown, not failure.** If a background implementer times out, inspect `git status`, the diff, and focused tests. It may have completed code but timed out during exhaustive verification. Continue from the real worktree state; do not discard or duplicate work solely because the agent returned no summary.
8. **Require explicit release closure.** A task is complete only after the final exact snapshot passes every required gate. Passing tests plus a failing review means the task remains in progress.

## Reviewer prompt checklist

Ask the reviewer to probe:

- direct INSERT/UPDATE/DELETE paths;
- old and new parent IDs during child reparenting;
- mutable valid-to-valid rerun fields excluded from identity hashes;
- whitespace controls (`space`, `tab`, `newline`, `carriage return`) across Python and SQL;
- populated partial schemas with invalid non-null values;
- atomic rollback of helper DDL, backfills, and constraints;
- real deployment invocation under concurrent migration;
- parent/child cross-row invariants after parent updates;
- terminal-state immutability and waiting-writer races.

## Evidence to retain

- RED failure count and exact blocker;
- focused and full test counts;
- migration-twice and concurrency results;
- exact commit hash and clean status;
- static scan scope;
- deterministic production before/after fingerprint;
- final review delegation ID and PASS/FAIL verdict.
