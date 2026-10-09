# Recovery-grade Wolfy architecture mapping

Use this procedure when asked to document or recover a live Wolfy/Hermes deployment spanning `/root/.hermes` and one or more Git worktrees. The goal is an evidence-backed map, not a design narrative.

## Evidence layers

Keep these layers separate throughout the report:

1. **Tracked source:** branch, exact commit/tree, migration files, wrappers, tests, plans.
2. **Live deployed source:** files actually present under `/root/.hermes`; do not assume a clean release worktree has been merged or copied there.
3. **Live runtime state:** Postgres relations/rows, Hermes cron configuration, profile SQLite stores, state artifacts, containers, and services.
4. **Historical evidence:** skills, old deployment notes, reverted commits, and prior test records. Historical evidence is not current deployment proof.
5. **Off-Git recovery material:** databases, state stores, source caches, release/canary/rollback artifacts, secrets, logs, and snapshots.

A recovery README should label every important claim by one of these layers.

## Audit sequence

1. **Map Git topology before reading architecture claims.**
   - Record `git status --short --branch`, `git branch -avv --no-abbrev`, `git worktree list --porcelain`, recent history, merge bases, and left/right commit counts.
   - Verify whether the release commit is contained in live `main` or any remote branch. A clean local release branch may still be local-only and absent from deployed source.
   - Preserve a dirty live worktree; never recommend a blind reset as recovery.

2. **Map profiles and scheduler ownership.**
   - Inventory global/default plus named profiles and their profile-local `config.yaml`, `SOUL.md`, scripts, `state.db`, and logs.
   - Parse `cron/jobs.json` into a compact table of ID, name, enabled state, schedule, wrapper, profile, and model. Do not expose prompts or secrets unnecessarily.
   - Distinguish profile directories from cron personas: a named worker such as Jonah or Sentinel may be a default-profile context job rather than a dedicated Hermes profile.
   - Report disabled jobs explicitly and search for the expected new publisher by name/script; absence is evidence that it is not scheduled.

3. **Trace the current pipeline from stable wrappers.**
   - Read the cron-facing wrapper, then the shared orchestration function it delegates to.
   - Verify ingest source, shard universe, readiness behavior, signal generation, recommendation writer, paper logger, outcome reviewer, and summary order from code.
   - Treat cron success as insufficient evidence of data completeness.

4. **Inventory Postgres from both source and live catalog.**
   - Group tables by coordination/knowledge, market data, strategy/governance, recommendations/accounting, and release-specific ledgers.
   - Check extensions, constraints, indexes, views, database size, and row counts for release-specific tables without dumping sensitive row data.
   - Compare migration files and hashes against live relations. A migration ledger can be incomplete even when relations and indexes exist; report this as a recovery hazard rather than claiming migrations are absent or unapplied.
   - Read live strategy status and explicit approval metadata. Skill text and plans are not current governance state.

5. **Inventory SQLite by role.**
   - Hermes `state.db` files store sessions/messages; Kanban and verification databases have separate roles.
   - Inspect the legacy Wolfy SQLite file in read-only mode and record its size/schema. A zero-byte ignored file is not a backup and must not be described as fallback data.
   - Keep historical compatibility schemas distinct from current authoritative storage.

6. **Verify release state fail-closed.**
   - Read the committed release artifact, CLI dispatcher, canary authorization, and rollback implementation.
   - Check for live copies of the artifact and executable adapter, canary evidence, rollback state, source cache, and scheduler entry.
   - Execute only a non-mutating disabled-artifact/safe-default probe when appropriate. Record the exact fail-closed result.
   - Read the actual production publication path: an option engine may exist in source while the bounded adapter deliberately passes no chain and therefore always selects stock fallback.
   - Verify whether rollback only writes a blocking state artifact or also edits cron/restores a prior publisher. If cron changes are external, say so explicitly.

7. **Audit dashboard and other auxiliary services as current or historical.**
   - Check tracked files, commit/revert history, live deployment directory, container/service presence, and current route before claiming a dashboard exists.
   - Historical deployment documentation plus reverted source and an absent deployment directory means “retired/historical,” not “currently deployed.”

8. **Run tests from the project test root.**
   - In a live Hermes repository with duplicated profile skill copies, repository-root pytest may collect same-basename tests from several profiles and fail with import-file mismatches.
   - Follow the project plan/source and run Wolfy tests from the `wolfy/` directory. If an overly broad root invocation fails, classify it as an invocation error only after the canonical scoped command passes.
   - Confirm the test harness redirects every implicit Postgres writer to exact `wolfy_test` before running the full suite.
   - Recheck Git status afterward to prove no tracked files changed.

9. **Separate automated verification from independent approval.**
   - A passing full suite, clean diff, and present production schema do not substitute for required independent spec/security review.
   - If a reviewer times out or hits a provider limit, report “review incomplete/unapproved”; do not promote it to approval from source quality or test success.

## Recovery README structure

Use this order so an operator can act under pressure:

1. Safety/status banner
2. Runtime and repository layout
3. Agents/profiles and ownership
4. Current ingestion/cron pipeline
5. Postgres schema map
6. SQLite/runtime-state map
7. Strategy engine and governance
8. Approved versus research sleeves
9. Options/fallback behavior
10. Allocator/risk/concurrency
11. Release/canary/scheduled/rollback mechanics
12. Dashboard and operations
13. Setup and canonical tests
14. Backup/restore procedure
15. Branches/commits/worktrees
16. Disabled/deferred components
17. Off-Git and secret-bearing artifacts
18. Verification summary and unresolved approvals

## Safe command patterns

Prefer commands that do not print credentials:

```bash
git -C /root/.hermes worktree list --porcelain
git -C <release-worktree> status --short --branch
hermes --profile default cron list --all
psql -X -d wolfy -c '\dt'
psql -X -d wolfy -c '\dv'
cd <release-worktree>/wolfy && python3 -m pytest -q
pg_dump -Fc -d wolfy -f /secure/recovery/wolfy.dump
```

For publication recovery, document bootstrap, canary, scheduled, and rollback commands with placeholder secure artifact paths. Never put DSNs, tokens, PINs, source-cache payloads, or enabled release artifacts into a public README.

## Common reporting traps

- Do not conflate “schema present” with “release activated.”
- Do not conflate “branch clean” with “deployed” or “pushed.”
- Do not infer current dashboards/services from historical notes.
- Do not call a legacy empty SQLite file a fallback backup.
- Do not omit off-Git state merely because the source tree is comprehensive.
- Do not claim rollback restores cron unless the implementation actually mutates cron.
- Do not publish secrets while trying to make the README recovery-complete.
- Do not bury the current activation state; put it in the first section.
