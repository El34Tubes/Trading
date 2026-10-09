# Auditable PostgreSQL Ledger Release Safety

Use this checklist when adding or reviewing authoritative run, ingestion, evaluation, recommendation, or outcome ledgers. A schema can satisfy its feature specification and still be unsafe as an audit record.

## 1. Terminal-state immutability

Once a parent run reaches a terminal/publication state, every fact used to justify that state must be immutable:

- parent status and identity;
- ingestion manifests and quality verdicts;
- derived-stage metadata;
- gate evaluations, terminal reasons, metrics, and provenance.

Enforce this in both layers:

1. Application helpers lock the parent row (`SELECT ... FOR UPDATE`) before every child insert/update/delete and reject writes when terminal.
2. PostgreSQL triggers reject direct SQL mutations to child rows when the parent is terminal.

Test the race, not only sequential calls: hold a child writer behind the parent lock, publish in another transaction, then verify the waiting writer rechecks status after acquiring the lock and fails.

## 2. Guard INSERT, UPDATE, DELETE, and reparenting

A readiness trigger on `UPDATE OF status` is incomplete. Direct `INSERT ... status='published'` can bypass it. Likewise, a child immutability trigger that checks only `NEW.run_id` permits `UPDATE child SET run_id=<mutable_parent>` to remove an authoritative fact from a published parent.

For terminal/readiness invariants:

- validate both `BEFORE INSERT` and relevant `BEFORE UPDATE` paths;
- on child `UPDATE`, lock and validate both `OLD.run_id` and `NEW.run_id` when they differ;
- reject deletion or mutation of supporting facts after terminal publication;
- reject published-parent identity updates and parent deletion, including cascades that would erase child facts;
- probe direct SQL for child reparenting, parent identity mutation, and parent deletion—not only ordinary child-column updates—because helper-level validation is not authoritative.

A useful adversarial probe matrix is:

1. update a published parent's evaluator/identity field;
2. move a manifest or gate from a published parent to a mutable parent;
3. delete the published parent and observe whether cascaded child deletion is blocked;
4. perform the inverse reparenting into a published parent;
5. verify all attempts fail while the transaction remains recoverable.

## 3. Upgrade populated partial schemas safely

`CREATE TABLE IF NOT EXISTS` plus `ALTER ... SET NOT NULL` is not a migration strategy when an earlier partial schema may contain rows.

For every added required column:

1. Add it nullable.
2. Backfill only when an old value has a deterministic canonical mapping.
3. Validate every existing row.
4. Fail with a clear migration exception for unmappable rows—never invent audit facts.
5. Add `NOT NULL`, checks, indexes, and triggers only after validation.
6. Apply the migration twice.

Test clean bootstrap and realistic populated prior versions of every affected table. Preserve IDs and source facts; do not drop data to make the migration pass.

Treat `CREATE TABLE IF NOT EXISTS` inline constraints as clean-bootstrap definitions only: they add nothing when a partial legacy table already exists. For each upgraded table, explicitly reconstruct every required `CHECK`, foreign key, uniqueness, and nullability contract with stable names, or prove an equivalent constraint already exists by definition rather than by name alone. After migration, inspect `pg_constraint` and run direct SQL against the upgraded partial table—not only a pristine table—to prove invalid future writes are rejected.

Validate the values of every pre-populated required field, not merely its non-nullness. Cover all affected tables, not only the table with the most complex backfill. In a ledger upgrade this commonly means adversarial legacy rows for parent identity/stage arrays and metadata, manifest counts/status/quality/provenance/payload identity/chronology, and gate taxonomy/JSON consistency. A legacy row with non-null but contradictory values (for example, a terminal reason outside its reason array or failed-gate JSON inconsistent with the decision) is still unmappable. Triggers created at the end of a migration protect only future writes; they do not retroactively validate existing rows. Add an explicit pre-constraint scan or validated constraint that examines every populated row.

Make the migration atomic and concurrency-safe in the deployment path itself. A test helper's advisory lock does not protect operators who run the SQL directly. Use a transaction plus a transaction-scoped advisory lock (or require and verify an equivalent migration runner). Exercise the real deployment invocation, including its stop-on-error and transaction flags. A late fail-closed exception must roll back earlier column additions and backfills rather than leave a partially applied schema. Treat backfilled audit timestamps and provenance as facts: only synthesize them when the mapping is explicitly canonical and documented.

## 4. Strict temporal contracts

Python `datetime` subclasses `date`. If a field means an exchange/session date, require `type(value) is date`; `isinstance(value, date)` is insufficient. Otherwise a timestamp may enter an identity hash while PostgreSQL coerces it to a timezone-dependent `DATE`, breaking deterministic idempotency.

Also validate chronology in Python and PostgreSQL:

- `completed_at >= started_at`;
- `available_at >= computed_at`;
- timestamps are timezone-aware in the required timezone/UTC contract;
- target/input sessions are pure dates.

## 5. Canonical JSON before writes

`json.dumps()` accepts `NaN` and infinities by default even though they are not portable JSON. Validate mappings with `allow_nan=False`, catch `TypeError` and `ValueError`, and raise the module's validation exception before any SQL executes. Cover nested values in metrics, provenance, gate facts, and failed-gate payloads.

After an invalid input, prove the transaction remains usable; a leaked driver exception that aborts the transaction violates fail-before-write behavior.

## 6. Canonical arrays and decision consistency

For authoritative reason arrays, enforce in PostgreSQL as well as Python:

- exact taxonomy/version;
- nonempty where required;
- sorted and unique;
- no null elements;
- pass/fail consistency (for example, pass means exactly `['passed']`);
- terminal reason belongs to the recorded set;
- JSON columns are objects/arrays of the specified shape.

Use rollback-wrapped direct SQL probes for unknown, duplicate, unsorted, empty, null-containing, and pass-inconsistent values.

## 7. Review sequence

Run two distinct gates:

1. **Specification review:** accepted fields, statuses, taxonomy, idempotency, readiness, and direct-SQL bypasses.
2. **Release-safety quality review:** terminal immutability, races, populated-schema upgrades, strict runtime types, nonfinite JSON, chronology, migration performance, and test flakiness.

A passing specification review does not replace the release-safety review.

## Evidence checklist

- [ ] Direct published INSERT rejected when unready
- [ ] Published parent identity/status updates and parent deletion rejected
- [ ] Child UPDATE cannot reparent a fact away from or into a published parent
- [ ] Published parent and all supporting child facts immutable
- [ ] Concurrent waiting writer cannot invalidate a just-published run
- [ ] Clean and populated partial-schema migrations pass or fail closed without data loss
- [ ] Existing non-null legacy values are fully canonical, not merely present
- [ ] Real deployment invocation wraps migration in a transaction and concurrency lock
- [ ] Late migration failure rolls back all earlier schema/backfill changes
- [ ] Migration applies twice
- [ ] Pure-date fields reject datetime
- [ ] Nonfinite JSON rejected before SQL; transaction remains usable
- [ ] Timestamp chronology enforced in Python and database
- [ ] Direct SQL cannot bypass canonical decisions
- [ ] Dedicated test database has no fixture residue
- [ ] Read-only production fingerprint is identical before and after
