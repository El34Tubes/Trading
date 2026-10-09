# Auditable Postgres Ledger Release Gates

Use this checklist when adding an append-like decision, evaluation, ingestion, provenance, or publication ledger to Wolfy.

## Model the ledger as an authoritative state machine

- Give each run a deterministic identity derived from an immutable identity tuple and enforce both the tuple and its canonical fingerprint.
- Runtime types must be exact where identity depends on them. Reject `datetime` for a pure session `date`; Python subclasses make permissive `isinstance(value, date)` unsafe.
- Define legal transitions explicitly. Protect them in both the Python API and Postgres, because direct SQL is part of the threat model.
- Publication is terminal. Once published, reject parent mutation/deletion and every child insert/update/delete that would change the published evidence.
- On child updates, inspect **both** `OLD.run_id` and `NEW.run_id`. Checking only the new parent permits reparenting evidence away from a published run.
- Freeze the complete rerun contract from insertion, not only the fields included in the identity hash. For example, `required_stage_names` may intentionally stay outside the hash yet must still be immutable; otherwise an identical application rerun becomes non-idempotent.
- Define one canonical-text predicate shared by Python and Postgres. Reject empty values and values padded with ASCII whitespace/control characters (`space`, tab, newline, carriage return, form feed, vertical tab). PostgreSQL `btrim(text)` removes spaces only by default, so it is not sufficient by itself. Apply the predicate to run identities, evaluator/version/universe fields, stage names, manifest source/version/reference fields, ticker, and strategy; retain uppercase enforcement where required.

## Canonical decision facts

- Keep one versioned reason taxonomy shared by Python, schema triggers, tests, and downstream analytics. Never invent aliases during an early task if a later accepted contract already defines the names.
- Enforce in Postgres as well as Python:
  - exact reason-code version;
  - nonempty sorted unique reasons;
  - passed rows have exactly `['passed']`;
  - failed rows exclude `passed`;
  - terminal reason belongs to recorded reasons;
  - failed-gate facts are consistent with reasons;
  - provenance/metrics/facts are JSON objects.
- Serialize JSON with `allow_nan=False`; convert `TypeError`/`ValueError` to the module’s validation error before issuing SQL. Test nested `NaN`, `+Infinity`, and `-Infinity`, then prove the transaction remains usable.

## Manifest invariants

Validate before writes and with database constraints/triggers:

- canonical nonblank dataset/provider/endpoint/entitlement/delay/parser/schema strings;
- target session equals the parent run’s immutable session;
- nonnegative expected/received symbol and row counts and retry count;
- exact status and quality-gate enums;
- completed manifests have `completed_at >= started_at`;
- provenance is a JSON object;
- exactly one canonical lowercase SHA-256 or nonblank immutable object reference.

Publication should require at least one completed, quality-passed, count-matched manifest for the target session plus complete canonical metadata for every required derived stage.

## Derived-stage provenance invariants

Treat nested `derived_stage_metadata` as authoritative before publication, not merely as a JSON object waiting for a later publish check. Validate it in the Python API, an always-active Postgres constraint/trigger, and populated-schema migration preflight.

For every present stage:

- the stage key is canonical and belongs to immutable `required_stage_names`;
- the value is an object with the exact persisted field set;
- `input_session` equals the parent run session;
- `computed_at` and `available_at` are canonical UTC timestamps with `available_at >= computed_at`;
- `transformation_version` and `universe_snapshot_id` are canonical text, and the universe ID equals the parent;
- `input_hash` is lowercase SHA-256;
- provenance is a JSON object with no nonfinite numbers;
- `source_run_ids` is a nonempty, lexicographically sorted, unique array of canonical strings.

Sorted source IDs are part of deterministic provenance. Checking only nonempty/unique values is insufficient: unsorted arrays can pass API, direct-SQL, and migration paths while representing the same logical inputs differently. Include the same unsorted vector (for example `['z-source', 'a-source']`) in all three regression paths. Empty top-level stage metadata may remain valid before any stage is recorded, but malformed present entries must fail immediately regardless of run status.

## Fresh install is not an upgrade test

`CREATE TABLE IF NOT EXISTS` does not add inline constraints to an existing table. Every schema feature needs both paths:

1. clean bootstrap;
2. populated partial-schema upgrade.

For upgrades:

- start an explicit transaction and take a transaction advisory lock;
- prevalidate all existing populated rows against the complete canonical contract before backfills or constraint replacement;
- never silently fabricate provenance or normalize invalid historical data;
- fail with a clear migration exception for unmappable rows;
- add missing columns and named constraints explicitly;
- prove a failed migration rolls back columns, backfills, and data changes;
- run valid upgrades twice and concurrently.

Do not backfill with `now()` before prevalidation if a later failure could leave nondeterministic partial state.

## Adversarial SQL test matrix

Beyond API tests, probe direct SQL for:

- published parent insert/update/delete;
- child insert/update/delete after publication;
- child reparenting both to and from a published run;
- nonpublished parent identity **and required-stage contract** mutation, both before and after children exist;
- empty or ASCII-control/whitespace-padded run, stage, manifest, ticker, and strategy identifiers (do not rely on space-only `btrim`);
- invalid reason ordering, duplicates, unknowns, pass mismatch, and scalar JSON;
- invalid manifest enums/counts/provenance/payload identity/session mismatch;
- populated invalid partial schemas;
- two-connection publication-versus-writer races.

Synchronize race tests using locks or observed lock waits, not fixed sleeps.

## Isolated verification order

1. Export the validated `wolfy_test` DSN **before** provisioning imports modules with module-level DSN constants.
2. In an isolated worktree, make that worktree's source directory the canonical first import path for the entire pytest session. Remove a distinct production source path, restore the local path at test boundaries, and fail closed if import-sensitive cached modules resolve outside the worktree. Legacy scripts may prepend an absolute production directory during collection or execution; a green focused test can otherwise be followed by a full suite that silently imports production code. Test module `__file__` origins as well as cached `DEFAULT_DSN` values.
3. Run focused RED/GREEN tests.
4. Apply schema twice and run populated partial-upgrade probes.
5. Run the full suite serially from the intended project scope (for example `pytest -q wolfy`); avoid repository-root collection when unrelated copied profiles contain duplicate test module names.
6. Run Ruff, compile, diff, secret/security, and broker-write scans.
7. Hash the read-only production invariant before/after; compare canonical hashes, not Python container identity after JSON tuple/list conversion.
8. Request snapshot-specific spec review, then code-quality review.

## Agent timeout and revision handling

A timed-out implementation subagent may have completed useful work but missed its report. Before discarding or restarting:

1. inspect `git status`, diff scope, and syntax/diff checks;
2. run the focused tests yourself;
3. if focused-green, finish full verification and commit directly;
4. if still RED, dispatch a narrowly scoped continuation naming the exact failures.

Limit each review loop to three revisions. On the third failed review, preserve the branch and ask the user whether to apply one explicit exception revision, pause, or accept the documented risk. Never treat a timeout alone as a failed quality verdict.
