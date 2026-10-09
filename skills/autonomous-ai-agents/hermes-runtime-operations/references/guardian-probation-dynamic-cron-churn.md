# Guardian probation and dynamic cron-state churn

Use this when a self-modifying Hermes job protects `config.yaml` and `cron/jobs.json` with a last-known-good guardian.

## Failure mode

`cron/jobs.json` contains both configuration and scheduler-owned runtime fields such as `completed`, `last_run_at`, `next_run_at`, and `updated_at`. A guardian that hashes the entire file and snapshots every healthy hash change may interpret ordinary scheduler churn as a new known-good state. During probation, that can silently replace the rollback anchor with a snapshot containing the unconfirmed config change.

A successful parse, healthy gateway, and `probation_active` message do not prove rollback safety. The key invariant is:

```text
manifest.latest_snapshot == probation.snapshot_path
```

The equality must still hold after at least one real periodic guardian tick and ordinary cron activity.

## Safe workflow

1. Snapshot the pre-change `config.yaml` and `cron/jobs.json`.
2. Apply exactly one reversible config/orchestration change.
3. Validate config parsing, `hermes cron list`, gateway health, and the target setting.
4. Write probation with the pre-change snapshot path.
5. Ensure the manifest hashes the probationary live state while `latest_snapshot` remains the pre-change snapshot.
6. After a real guardian tick and cron activity, re-read both files and assert the rollback-anchor equality above.
7. If the anchor moved to a probationary snapshot, treat probation as unsafe: immediately restore the original pre-change snapshot, clear probation, revalidate cron/gateway/config, record `config_rollbacks=1`, block the task with a permanent no-identical-retry lesson, and do not report the change as completed.
8. If policy forbids the current optimizer from editing guardian code, do not work around that prohibition. Keep orchestration unchanged and choose a non-config task until an authorized path repairs the guardian.

## Design guidance for an authorized guardian maintainer

Separate stable declarative job configuration from scheduler-owned runtime fields before change detection. A practical canonical hash should:

- drop top-level `updated_at`;
- drop per-job `next_run_at`, `last_run_at`, `last_status`, `last_error`, `last_delivery_error`, `fire_claim`, and transient start/run timestamps;
- normalize non-paused `state` values such as `scheduled` and `running` to one active value, while retaining `paused` as declarative intent;
- drop `repeat.completed` while retaining `repeat.times`;
- preserve meaningful fields such as `enabled`, schedule, prompt, script, profile, model/provider, delivery, and toolsets.

During active probation, never promote a healthy changed snapshot automatically. Refresh only the manifest's observed live hashes while preserving `latest_snapshot` as the explicit pre-change rollback anchor until next-run confirmation.

Add two regression tests:

1. Mutate only scheduler runtime fields and prove the declarative cron hash is unchanged.
2. Apply a probationary config change plus cron runtime churn, run the guardian, and prove both `manifest.latest_snapshot == probation.snapshot_path` and that no new snapshot directory was created.

For live verification, run the guardian twice and compare the manifest's `latest_snapshot` path before and after; snapshot-directory counts alone are insufficient when bounded retention keeps the count constant.

## Reporting

Report the attempted commit and rollback commit separately. Final state must name the restored value, absent probation marker, healthy guardian/cron checks, failed or blocked task/run state, and the permanent no-retry reason.