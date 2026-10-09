# Exact-Snapshot Source Publication and Disabled-Activation Audit

Use this checklist when reviewing a committed release that combines database code, a paper-production adapter, public recovery material, and disabled scheduler state. It extends the database invariant gate with adversarial static and rollback-safe probes.

## 1. Audit the Git object, not merely the checkout

- Pin the requested commit and confirm the checkout is exactly that commit and clean before and after.
- Use `git ls-tree`/`git show <commit>:<path>` for publication-boundary claims, because ignored or untracked live files in the checkout are not part of the published tree.
- Scan the complete committed tree for merge markers; exclude binary/lock artifacts only deliberately.
- Distinguish root live configuration from profile-local configuration. If the requirement says no tracked `config.yaml`, enumerate every matching path rather than checking only the root.

## 2. Separate publication readiness from activation readiness

Return two verdicts:

- **Source publication:** secrets, runtime-state sanitization, recovery-document accuracy, coherent migrations/compatibility contracts, and code correctness.
- **Production scheduler activation:** default-disabled state, canary authorization, idempotent recurring behavior, exact approved strategy scope, single-writer guarantees, and production invariants.

A default-disabled adapter can be safe to publish while still being unfit to activate; conversely, leaked runtime metadata can block publication even when execution remains disabled.

## 3. Probe bidirectional compatibility aliases adversarially

For dual legacy/current identifiers such as `legacy_id` and `sqlite_id`, do not stop at inserts where one side is NULL. In a dedicated test database and a transaction that is always rolled back:

1. insert through each alias separately and require equality;
2. update only the first alias and inspect both;
3. update only the second alias and inspect both;
4. provide conflicting non-NULL values and require deterministic reconciliation or rejection;
5. seed conflicting populated legacy rows and confirm migration behavior is explicit.

A trigger using `NEW.a := COALESCE(NEW.a, NEW.b); NEW.b := COALESCE(NEW.b, NEW.a)` does not synchronize one-sided updates when both values were already non-NULL. Tests named “both directions” must include UPDATE cases.

## 4. Treat numeric range as part of JSON cast hardening

Regex syntax checks before `::integer` or `::bigint` do not prevent `NumericValueOutOfRange`. Probe:

- nonnumeric strings;
- fractional strings;
- signed values according to policy;
- integer and bigint boundary values;
- digit-only values beyond the destination type’s range.

If malformed/out-of-range compatibility data should degrade to NULL, use a bounded conversion helper or guarded exception handling rather than regex alone. Exercise both migration backfills, trigger paths, and compatibility views.

## 5. Verify recurring mode after a successful canary

Do not test only the first canary. Model the next scheduler invocation with already-persisted recommendation identities. A recurring path must accept an idempotent zero-create result for an already-published exact scope, or deliberately advance to a new authorized session/snapshot. Reusing a canary validator that requires the first callback to create rows can make scheduled mode permanently fail after canary success.

Test the sequence: disabled artifact → bootstrap/authorization → canary creates rows → canary rerun creates zero → first scheduled invocation → later scheduled invocation → rollback blocks future scheduling.

## 6. Audit public scheduler sanitization structurally

Parse the public inventory and compare it with the private/live shape without printing secret values. Confirm:

- every public job is disabled;
- delivery is local and destinations/webhooks/channel IDs are absent;
- last/next-run timestamps, errors, state blobs, model/provider snapshots, and other telemetry are absent;
- stable live identifiers and counters such as `repeat.completed` are removed or deliberately regenerated if the documentation claims operational state is private;
- no credentials, emails, IPs, private URLs, or host-specific paths remain unless explicitly allowed.

Validate README claims against these exact fields. “Valid JSON” and “all jobs disabled” are necessary but not sufficient to call an inventory sanitized.

## 7. Production-safe test evidence

Before scanner or persistence-focused tests, capture a production snapshot using database-enforced read-only mode. Include scanner tables, recommendation/paper tables, strategy counts, and the full approved-strategy governance row. Run tests only with an exact validated dedicated DSN, then compare literal before/after snapshots. Keep all adversarial database probes transactional and roll them back.

## 8. Freeze every writer before the final recovery snapshot

A successful dump is not necessarily a coherent final snapshot when scheduled jobs or watchdogs can write between database, SQLite, and runtime-archive phases.

1. Inventory **all** writers: source/config mutators, database ingestion and cleanup jobs, no-agent scripts, external workers, and watchdogs that can automatically resume paused jobs.
2. Pause or otherwise quiesce them before the first final dump. Pausing only source-mutating jobs is insufficient when database writers remain active.
3. Re-list scheduler state immediately before backup and again after backup. Never rely on an earlier pause result; an autorecovery or quota watchdog may have resumed jobs.
4. Capture the exact private scheduler file only after definitions are stable. Preserve definitions privately even if every public recovery entry is disabled.
5. Use the order: quiesce writers → verify quiescence → PostgreSQL dump → SQLite online backups → explicit-allowlist runtime archive → encryption → restore verification.
6. If any writer runs or resumes during that interval, label the result intermediate, freeze writers again, and repeat the affected snapshot. Do not describe it as the final point-in-time recovery set.

## 9. Prove recovery at every boundary

- Validate SQLite source backups with `PRAGMA quick_check`, then decrypt/extract the encrypted archive and validate the recovered copies again.
- For PostgreSQL dumps containing extensions, create required extensions as a superuser in the temporary target, filter extension ownership/comment entries from the `pg_restore --list` manifest, restore the application-owned objects as the application role, and compare critical row/schema/extension counts.
- Compare plaintext hashes before and after local encryption/decryption.
- Upload only encrypted binary artifacts to private off-server storage. Download each artifact back through authenticated access and compare both byte size and SHA-256; an upload response alone is not verification.
- Keep the recovery key outside the artifact repository and release. Server deletion remains blocked until a human confirms separate off-server key custody.
- Clone the public source repository from its remote, assert the exact recovery SHA/tag, and run the authoritative suite in that clean clone.

## 10. Preserve finality across late audit findings

Do not call a pushed commit or tag final until exact-snapshot review is complete. If review discovers blockers after publication:

1. mark the existing tag as preliminary rather than silently treating it as authoritative;
2. fix and test the findings in a new commit;
3. create a new unambiguous final tag (prefer this over moving an already-published tag);
4. update the private recovery manifest to the new source SHA;
5. repeat clean-clone and public/private remote verification.

A restore-tested database archive does not make a system wipe-ready when the final source commit is still dirty, encrypted assets have not round-tripped from off-server storage, or the separate key has not been transferred.

## Reporting

List blockers first with `file:line`, a concrete consequence, and reproduction evidence. Then summarize passed controls. State test scope precisely and confirm that the exact HEAD and clean tree remained unchanged. Distinguish intermediate local backups, locally restore-tested encrypted assets, remotely uploaded assets, and remotely downloaded/hash-verified assets. Never collapse these into a single “backed up” claim, and never imply separate key custody without explicit confirmation.