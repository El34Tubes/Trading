# Probationary cron edits without promoting unconfirmed state

Use this pattern for one reversible Hermes cron/config mutation protected by a periodic config guardian.

## Hazard

A guardian that snapshots every healthy hash change can accidentally promote the newly edited, still-unconfirmed configuration on its next 15-minute tick. If expiry later restores the newest snapshot, it may restore the probationary state instead of the pre-change state.

## Safe sequence

1. Run the deterministic budget gate and guardian health check first. A blocked budget gate means plan-only; do not mutate orchestration.
2. Confirm no prior probation is unresolved and stay outside protected job windows.
3. Claim the durable task and start its run.
4. Before editing, copy both `config.yaml` and `cron/jobs.json` into one timestamped `guardian/known_good/<UTC>/` directory. Record hashes and the reason.
5. Apply exactly one reversible change through the Hermes CLI when possible (for example, `hermes cron edit <id> --schedule '0 * * * *'`). Never alter the optimizer's own schedule.
6. Create `probation.json` with the change, task/run IDs, pre-change snapshot path, confirmation deadline near the next optimizer run, and `confirmed: false`.
7. If the guardian uses a hash manifest to detect changes, set its observed hashes to the probationary live files **while keeping `latest_snapshot` anchored to the pre-change snapshot**. This prevents the periodic guardian from creating a new “known-good” snapshot of unconfirmed state while preserving a real rollback target. Do not change guardian code or loosen its checks.
8. Validate immediately:
   - YAML and cron JSON parse.
   - Target job is enabled and has the exact schedule plus valid `next_run_at`.
   - Optimizer remains enabled.
   - `hermes cron list` exits 0.
   - Guardian reports `probation_active`.
   - Gateway is healthy.
   - `manifest.latest_snapshot == probation.snapshot_path`, and both protected files exist there.
9. In a dirty live-state repository, stage only the intended schedule keys with a minimal `git apply --cached` patch; do not stage mutable counters, timestamps, unrelated job removals, or other workers' edits. Stage at most one concise ledger note as the second file. Run `git diff --cached --check`, exact staged-name assertions, and a staged secret-pattern scan.
10. Record measured/projected KPIs before task completion, commit locally, save the full commit hash and verification result, then close task and run.
11. On the next optimizer run, confirm the optimizer ran on schedule and gateway/job health remained good. Promote/clear probation only then. If health failed, retain/verify rollback and record the identical change as non-repeatable.

## Cadence projection

For a cron cadence change, calculate scheduled starts deterministically (for example, every 20 minutes = 72/day; hourly = 24/day) and label this as a projection, not observed LLM usage.

## Verification pitfall

A successful `hermes cron edit` changes runtime fields such as `next_run_at` and mutable completion counters may already differ from Git HEAD. A whole-file `git add cron/jobs.json` can commit unrelated live state. Build the index patch from the HEAD context and include only the schedule fields that define the intentional change.
