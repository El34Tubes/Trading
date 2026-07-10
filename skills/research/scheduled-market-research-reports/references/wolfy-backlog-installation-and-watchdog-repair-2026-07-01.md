# Wolfy backlog installation + stale quota watchdog repair — 2026-07-01

Use when the user provides a one-time Wolfy backlog/architecture/data-quality installation prompt and asks Hermes to enact it under the EOD/Postgres-only constitution.

## What was installed

- Inserted the user-approved DQ/VAL/LRN backlog verbatim into `/root/.hermes/wolfy/optimization_todo.md` immediately after `## Operating constraints` and before the first dated daily-run heading.
- Created `/root/.hermes/wolfy/DATA_QUALITY_STANDARDS.md` verbatim.
- Persisted planning-only Postgres `agent_tasks` rows for all requested backlog items with:
  - `agent_name='wolfy'`
  - `task_type='optimization'`
  - `status='queued'`
  - deterministic `source_fingerprint='user-approved-20260701-<code>'`
  - payload including code/tier/source/sequencing order and an explicit “do not implement this run” intent.
- Counts created/upserted: DQ=6, VAL=4, LRN=4, ARCH=6, R=6, WATCH=5.
- Committed and pushed in narrow verified commits:
  - backlog insert
  - data-quality standards doc
  - close-out ledger entry

## Verification pattern

- Verify exact prompt installation by extracting the source prompt’s fenced sections and checking:
  - backlog block is exactly present in `optimization_todo.md`
  - standards file exactly equals the source block
- Verify task persistence with a grouped Postgres query over `source_fingerprint LIKE 'user-approved-YYYYMMDD-%'`.
- Verify git with `git log --oneline -3 --decorate` and pushed `origin/main` state.
- Keep unrelated dirty working-tree files out of commits; this environment often has unrelated profile/curator/guardian churn.

## Watchdog repair lesson

The old usage-limit watchdog can falsely claim a provider limit when stale or undated quota lines remain in logs/state. In this session:

- `usage_limit_watchdog_state.json` claimed `limited_active=true`.
- A minimal live provider probe (`hermes chat -q 'Reply exactly: OK' --toolsets safe`) succeeded.
- The allowed one-time repair backed up the state file, set `limited_active=false`, cleared `limit_resets_at`, recorded the repair reason, and reconciled enabled optimizer job `92f31b95fccc` out of `paused_llm_jobs`.

Future WATCH implementation requirements:

- Treat quota evidence as active only if timestamped/fresh and anchored to a reset time.
- Do not count undated historical traceback/payload lines as today.
- Exclude watchdog-emitted lines from later scans and avoid echoing raw quota substrings into cron output.
- Reconcile paused state against `cron/jobs.json` every tick; do not keep enabled jobs listed as paused-by-watchdog.
- Prefer a deterministic budget gate as the primary signal; log scanning should be secondary evidence.

## Close-out report shape

For this class of one-time Wolfy installation run, close with:

- FACT: files changed, commit hashes, push confirmation, task counts by prefix, watchdog state before/after, and live provider probe result.
- JUDGMENT: top 3 current risks tied to backlog item IDs.
- RECOMMENDATIONS FOR HUMAN: Tier B asks only.
- NEXT ACTION: next optimizer task, usually DQ-1 unless Priority-1 data health or WATCH regression blocks it.
