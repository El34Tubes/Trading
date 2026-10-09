# Plan-spec compliance review for PostgreSQL ledgers

Use this when reviewing an exact commit that introduces an authoritative run/state ledger. The focused pytest suite is evidence, not the verdict: independently probe the database boundary against the complete accepted plan.

## 1. Freeze the review target

- Verify exact `HEAD`, clean worktree, and requested base-to-head diff.
- Read both the task block and earlier cross-cutting contracts in the accepted plan. Definitions and canonical vocabularies are often specified outside the task itself.
- Map each requirement to a schema object, application helper, test, or explicit later task. Flag invented policy that conflicts with a later task as overreach.

## 2. Build a requirement matrix

At minimum, account for:

- every required table, field, index, foreign key, uniqueness rule, and check;
- deterministic identity and concurrent idempotency;
- every legal and illegal state transition;
- insert-time, update-time, and post-transition invariants;
- canonical/versioned reason vocabulary and pass/fail consistency;
- JSON object shape and serializability;
- exact timestamps, counts, hashes/object references, source/provenance fields;
- derived-stage completeness and linkage to immutable run identity;
- transaction ownership, rollback behavior, and absence of internal commits;
- migration applicability to a **populated plausible prior/partial schema**, followed by second-run idempotency;
- application/database coercion parity for pure dates, timestamps, JSON numbers, arrays, and canonical strings;
- test-database isolation and production invariants.

## 3. Probe the authoritative database directly

Application validation is insufficient for Postgres-authoritative systems. Wrap adversarial probes in `BEGIN ... ROLLBACK` against the dedicated test database.

Test at least:

1. **INSERT bypass:** Can a terminal/published row be inserted directly without prerequisites? An `UPDATE OF status` trigger does not cover INSERT.
2. **UPDATE bypass:** Can an illegal transition be performed directly?
3. **Canonical arrays:** Can direct SQL store unknown, duplicate, unsorted, or pass-inconsistent reason codes?
4. **Empty identities/references:** Can `''` or whitespace satisfy a nominally non-null immutable reference or identity?
5. **Post-terminal mutation:** After publication, can required metadata or the only passed manifest be downgraded/deleted, leaving an invalid published row? Exercise the public upsert APIs as well as direct SQL. Also test a writer that begins before publication and resumes after the finalization lock commits; a pre-lock status check is stale.
6. **JSON shape and numeric validity:** Can arrays, scalars, JSON null, `NaN`, or infinity enter object-only fields? Python's `json.dumps()` accepts non-finite floats unless `allow_nan=False`, while PostgreSQL JSON rejects them and aborts the transaction.
7. **Date/time coercion:** Pass a timezone-aware `datetime` where the API contract requires a pure `date`. Reject it before hashing or persistence: `datetime` subclasses `date`, its full timestamp can enter an identity hash, and PostgreSQL/session timezone coercion can store a different calendar date.
8. **Temporal consistency:** Reject completion before start and mismatched target/input sessions at both application and database boundaries.
9. **Populated partial-schema upgrade:** Recreate the plausible previous table shape, insert representative legacy rows, then apply the migration. `CREATE TABLE IF NOT EXISTS` does not add missing columns, and `ADD COLUMN` followed immediately by `SET NOT NULL` fails without a backfill/default strategy.
10. **Concurrent create:** Run several committed connections against one identity; require one stable ID and one row.

A transition-time check establishes only a momentary condition unless later writes cannot invalidate it. Decide from the plan whether publication must remain valid, then probe accordingly. For final-state immutability, parent transition triggers are insufficient by themselves: child-table updates and same-status parent metadata updates need their own guards or a parent-lock/status-check protocol in the same transaction.

## 4. Compare canonical contracts literally

Do not accept semantically similar invented names when the plan declares a canonical vocabulary. Compare exact spellings and version semantics. A reduced or renamed enum can make later tasks incompatible even if current tests pass.

Also compare any plan-level example schema that is presented as a contract. If the task block is terse, earlier architecture/observability sections remain binding unless explicitly deferred.

## 5. Verification evidence

Run and report separately:

- focused tests;
- schema application twice;
- concurrency probe;
- direct-SQL negative probes;
- changed-file lint/compile/diff checks;
- zero test-fixture residue;
- read-only production identity/invariant check;
- final exact `HEAD` and clean-tree recheck.

Return one blocking-only PASS/FAIL. Passing tests do not override a successful adversarial bypass. Do not modify the reviewed snapshot unless repair was explicitly requested.
