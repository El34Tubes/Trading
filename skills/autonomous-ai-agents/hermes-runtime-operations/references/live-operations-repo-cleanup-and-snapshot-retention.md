# Live operations repository cleanup and bounded recovery snapshots

Use this pattern when a Git repository is also the live application home, so source, scheduler wrappers, credentials, runtime state, snapshots, and generated research artifacts coexist.

## Classification before deletion

1. Inspect tracked, modified, untracked, and ignored files separately.
2. Cross-check active cron/scheduler script references, imports, subprocess call sites, documentation, automation allowlists, and profile wrappers.
3. Inspect artifact age, size, and provenance.
4. Treat OAuth/token directories, active databases, scheduler state, current config, live caches, and required profile wrappers as operational state. Ignore them in Git where appropriate; do not delete them merely because they are untracked.
5. Restore any tentatively removed tracked script if an allowlist, README, migration note, wrapper, or subprocess path still references it.

Safe cleanup classes after evidence include ignored `tmp_*` probes and outputs, Python/test caches, obsolete nested Git backups, stale one-off smoke bundles, downloaded source copies whose distilled content is persisted, dated status handoffs superseded by durable state, and explicitly obsolete pre-update snapshots.

## Fix unbounded snapshot growth

If a guardian creates a recovery snapshot on every run, one-time deletion is insufficient:

1. Confirm rollback selection and protected paths.
2. Add retention only after the new snapshot and manifest are successfully written.
3. Use collision-resistant snapshot names (microseconds or another unique suffix), and store authoritative `created_at` metadata inside each snapshot.
4. Sort retention by snapshot metadata, not directory mtime. Touching or copying an old directory must not make it appear new; malformed/missing metadata should sort oldest and be pruned first.
5. Keep a bounded recovery window suitable for run frequency (for example, latest 24).
6. Test exact membership rather than only count:
   - create more than the limit;
   - assert the oldest snapshots no longer exist;
   - assert the newest snapshots are exactly the retained set;
   - assert the manifest points to the newest snapshot;
   - touch an old directory and prove it is still pruned.
7. Apply retention to the accumulated live directory without invoking unrelated config or cron mutation.

## Verification

- Run project tests from the project directory. Repository-root pytest can collect synchronized copies of identical test modules and raise import-file mismatch errors; that is collection topology, not necessarily a product failure.
- Compile affected operational scripts and run focused `git diff --check`.
- Smoke the guardian/scheduler and critical integrations after cleanup.
- In a dirty operations repo, stage only focused cleanup paths and inspect staged names and diff before committing.
- Report reclaimed bytes, remaining scratch count, retained snapshot count, tests, commit hash, and push status.

## Pitfalls

- Names such as `sync_*`, `init_*`, and `queue_*` do not prove obsolescence.
- Ignored secrets are not disposable clutter.
- Do not reset unrelated profile, skill-sync, config, cron, or active feature changes to make the tree appear clean.
- Ignored recovery data still consumes disk; retention must be enforced in the producer.
