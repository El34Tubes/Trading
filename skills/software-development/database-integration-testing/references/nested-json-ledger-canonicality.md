# Nested JSON Ledger Canonicality

Use this review pattern when canonical ledger fields are embedded inside a JSON/JSONB document rather than stored as ordinary columns.

## Failure mode

A schema may correctly validate scalar columns and required-name arrays yet accept malformed nested stage metadata before terminal publication. A common incomplete trigger validates only:

- the outer value is a JSON object;
- the required-stage array is canonical;
- nested fields only when status changes to a terminal state.

That leaves authoritative preterminal rows vulnerable to direct SQL containing padded stage names, transformation versions, source-run IDs, or universe IDs. Likewise, a partial-schema migration that checks only `jsonb_typeof(document) = 'object'` can preserve malformed populated documents and still commit successfully.

Green application tests do not close this bypass because application writers may validate before issuing SQL.

## Targeted release probes

Run both probes in a dedicated test database and wrap ordinary writes in rollback-safe transactions.

1. **Preterminal direct-SQL probe**
   - Create a canonical nonterminal parent row.
   - Directly replace the nested JSON document with otherwise complete metadata containing one edge-padded value such as `transformation_version='\tbad'`.
   - Require the database write itself to fail; rejection only during later publication is insufficient when the table is the authoritative ledger.
   - Repeat representative cases for object keys/stage names, transformation version, source IDs, and copied universe identity.

2. **Populated partial-schema migration probe**
   - Create the oldest supported partial schema with a populated nonterminal/evaluated row.
   - Put a malformed but structurally object-shaped nested document in it.
   - Apply the real migration entry point.
   - Require failure and literal pre/post equality of tables, constraints, and namespace-local helper functions, proving DDL and backfills rolled back atomically.

3. **Array-invariant independence probes**
   - Do not collapse “nonempty, canonical, unique, sorted” into one generic array test. Exercise each property with an input that satisfies the other three.
   - For ordering, use an unsorted-but-otherwise-valid value such as `['z-source', 'a-source']`; duplicate, empty, padded, and non-string cases cannot reveal a missing sort check.
   - Run the ordering counterexample through all three enforcement surfaces: the application writer, direct SQL, and a populated partial-schema migration.
   - For authoritative tables whose trigger applies across lifecycle states, exercise direct-SQL `UPDATE` in every mutable/nonpublished status and probe direct `INSERT` separately. One evaluated-row update does not prove every trigger path is covered.
   - Pair every negative probe with a positive sorted value such as `['a-source', 'z-source']`. Require it to pass, then re-read the JSON array to prove order is preserved unchanged rather than silently normalized.
   - For the migration probe, compare literal pre/post schema-and-row snapshots after the expected failure; then migrate a separate sorted fixture and assert exact metadata equality. Always remove temporary schemas in `finally`.
   - Require all three enforcement surfaces to reject the unsorted value. If the API, database predicate, or migration accepts it, the release gate fails even when the focused suite is green.
   - Inspect both layers for the same omission: application code often compares only `len(set(values))`, while SQL often compares only `count(*)` with `count(DISTINCT ...)`. Neither expression proves canonical ordering.

4. **Terminal regression probe**
   - Keep existing publication checks, but do not treat them as substitutes for write-time and migration-time validation.

## Implementation guidance

Centralize the nested-document predicate in a PostgreSQL helper where practical, then invoke it from:

- migration preflight over every populated legacy row;
- `BEFORE INSERT OR UPDATE` triggers in every lifecycle state;
- terminal publication validation for defense in depth.

The predicate should validate exact keys where the contract requires them, canonical object keys, scalar types, canonical text boundaries, nonempty/unique/sorted arrays, copied parent identities, hashes, dates/timestamps, and JSON object fields. Treat array cardinality, element validity, uniqueness, and ordering as distinct predicates and tests. Decide explicitly whether extra top-level stage keys are allowed; test that decision directly rather than silently ignoring extras.

## Review reporting

If a direct SQL probe prints an accepted malformed nested value or the migration commits malformed populated JSON, report one blocking finding with both reproductions. Cite separately:

- the migration preflight that checks only outer JSON type; and
- the trigger branch that defers nested validation until terminal status.

This remains a blocker even when the full application test file is green.