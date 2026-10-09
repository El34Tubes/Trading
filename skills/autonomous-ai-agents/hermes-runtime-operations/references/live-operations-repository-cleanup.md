# Live operations repository cleanup

Use this pattern when the Git repository is also the active Hermes/application state directory and cron jobs, OAuth clients, profile synchronizers, or watchdogs mutate files continuously.

## Conservative classification

1. Capture Git truth and live references before deleting:
   - tracked vs untracked vs ignored;
   - imports and textual references;
   - active cron script names and profile/global wrappers;
   - open file descriptors for candidate payloads;
   - autorepair/synchronization allowlists.
2. Treat ignored as "not for Git," not automatically disposable.
   - OAuth token stores, scheduler heartbeat markers, state databases, profile-installed skills, and cron state can be ignored but operationally essential.
   - One-off `tmp_*` probes, generated command output, caches, and completed download artifacts are usually removable after reference/open-file checks.
3. Do not delete tracked compatibility scripts merely because the canonical system has migrated. Retain them when a documented inbox, test fixture, manual operator path, wrapper, or latent source reference still depends on them.
4. Remove tracked one-shot utilities only when all are true:
   - no importers, cron jobs, wrappers, allowlist entries, or current callers;
   - Git history shows a bounded migration/verification purpose;
   - the current replacement workflow is identifiable;
   - affected tests pass after deletion.

## Storage hotspots

Measure before pruning. High-value targets often include accumulated scratch probes, nested local Git backups, stale integration-smoke bundles, old rollback snapshots, unbounded guardian snapshots, and obsolete pruning/log backup bundles.

Use retention instead of indiscriminate deletion for rollback material.

## Deterministic snapshot retention

For timestamped known-good snapshots:

- Use collision-resistant names (microseconds or another unique suffix).
- Store authoritative `created_at` metadata.
- Sort retention by metadata, not directory mtime; touching or copying an old directory must not make it new.
- Keep a bounded count appropriate to snapshot cadence.
- Test exact membership, not only count:
  - create more than the limit;
  - assert the oldest set is gone and newest set remains;
  - assert the manifest points to the latest snapshot;
  - touch an old directory and prove it is still pruned.

## Open-file safety

Before removing generated payloads, inspect open descriptors with `lsof <candidate>` or `lsof +L1`. Linux preserves an existing reader's descriptor after unlink, but checking first avoids surprising active transfers and allows cleanup to wait when appropriate.

## Verification and commit isolation

- Run tests from the actual project directory. Repository-root `pytest` can accidentally collect duplicated profile-installed skill tests with identical module names; that is not the project suite.
- Compile affected scripts and use focused `git diff --check -- <paths>` so unrelated dirty files do not obscure cleanup verification.
- Stage only cleanup paths and inspect `git diff --cached --name-status` before committing.
- Report pre-existing dirty runtime/profile changes separately; do not erase or bundle them into the cleanup commit.
