# Deterministic PostgreSQL Identity Contracts

Use this pattern when an application derives an immutable row identity from canonical JSON and stores only its digest.

## Threat model

A unique `run_identity` column is insufficient when direct SQL can:

- insert an arbitrary 64-character digest;
- mutate one identity input while retaining or replacing the digest;
- mutate a parent session after child rows have copied it;
- preserve bad legacy identities during a partial-schema migration.

The database must independently recompute the digest and freeze every identity input immediately after insert, not only after a terminal status.

## Canonical parity

First document the application serialization exactly. For Python:

```python
json.dumps(payload, sort_keys=True, separators=(",", ":"))
```

The defaults matter: `ensure_ascii=True` escapes non-ASCII code points, with supplementary-plane characters represented as UTF-16 surrogate pairs. PostgreSQL `jsonb::text` is not byte-identical: whitespace and Unicode rendering differ. Do not hash `jsonb::text` and assume parity.

A robust SQL implementation should:

1. Serialize each text scalar with JSON escaping for quote, backslash, short control escapes, other controls as `\\uXXXX`, BMP non-ASCII as `\\uXXXX`, and supplementary code points as high/low surrogate pairs.
2. Construct the object in the exact sorted key order with compact separators.
3. Format dates explicitly as `YYYY-MM-DD`; do not rely on session `DateStyle`.
4. Hash UTF-8 bytes with PostgreSQL's built-in `sha256(bytea)` when supported, then `encode(..., 'hex')`. This avoids requiring `pgcrypto`; if the supported PostgreSQL baseline lacks core `sha256`, provision and verify `pgcrypto` explicitly.
5. Declare the helper `IMMUTABLE STRICT` only when every operation is genuinely independent of session settings.

## Migration and trigger contract

Inside one explicit migration transaction, under the migration advisory lock:

1. Create/replace the deterministic helper.
2. Before any backfill or constraint replacement, scan every existing row with `stored_identity IS DISTINCT FROM recomputed_identity`.
3. Abort on the first invalid legacy population.
4. Install a `BEFORE INSERT OR UPDATE` trigger:
   - INSERT: stored digest must equal recomputed digest.
   - UPDATE: reject changes to the digest or any identity input, regardless of status.
   - Preserve stricter terminal-state errors/no-op semantics where already defined.
5. Keep mutable readiness/configuration fields outside the identity only when that exclusion is intentional and tested.

Because helper creation is inside the same explicit transaction, an invalid legacy row must roll back the helper DDL as well as table changes. Test namespace-local function absence after rollback when the database also has a public helper of the same name.

## Required tests

- Known Python/SQL vector containing quotes, backslashes, controls, BMP Unicode, and supplementary Unicode.
- Deterministic randomized parity probe across many PostgreSQL-valid text vectors (PostgreSQL `text` cannot contain NUL).
- Direct insert with an arbitrary valid-looking lowercase SHA-256 digest fails.
- Direct update of each identity field fails immediately after insert.
- Identity mutation fails in every lifecycle status, not only the published/terminal status.
- Parent session cannot diverge from already-persisted child session facts.
- Populated partial schema with a valid-looking but incorrect digest fails atomically.
- Existing valid rows migrate, schema applies twice, concurrent migrators serialize, and application reruns remain idempotent.

## Verification evidence

Report separate evidence for:

- RED failures proving the bypasses existed;
- focused ledger suite;
- full serial suite;
- migration-twice and concurrent migration coverage;
- Python/SQL parity vectors;
- changed-file lint/compile/diff checks;
- read-only production invariants before/after;
- explicit staged files and final commit hash.
