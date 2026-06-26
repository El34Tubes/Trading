# Wolfy visible progress ledger backlog-hygiene snapshot (2026-06-21)

Pattern for the daily Wolfy optimization planner when backlog hygiene is a priority but active allocator/stale-cleanup jobs make task mutation risky.

## Context

The daily optimizer had to identify safe high-value Wolfy/Hermes optimizations, avoid stepping on cron jobs, and keep scope under the two-file throttle. Frequent no-agent jobs were due within minutes, including stale coordination cleanup and safe autorepair, so mutating `agent_tasks`/Kanban state was deferred.

## Safe bounded optimization

Extend deterministic read-only status helpers such as `/root/.hermes/wolfy/visible_progress_ledger.py` with a backlog-hygiene snapshot instead of editing task state directly:

- Query Postgres `agent_tasks` only in read mode.
- Count active work by status: `queued`/`ready`, `in_progress`, `blocked`.
- Count stale `in_progress` rows using a conservative threshold such as `updated_at < now() - interval '6 hours'`.
- Count duplicate active `source_fingerprint` values across `queued`, `ready`, `in_progress`, and `blocked` rows.
- Surface the facts in the Markdown Snapshot table as `Backlog hygiene`.
- If stale/duplicate counts are nonzero, make the next action a bounded backlog-hygiene pass, but explicitly wait until allocator/stale-cleanup jobs are idle and avoid mutating active claims.

Example query shape:

```sql
WITH active AS (
  SELECT *
  FROM agent_tasks
  WHERE status IN ('queued','ready','in_progress','blocked')
), duplicate_fingerprints AS (
  SELECT source_fingerprint
  FROM active
  WHERE source_fingerprint IS NOT NULL
  GROUP BY source_fingerprint
  HAVING count(*) > 1
)
SELECT count(*) FILTER (WHERE status IN ('queued','ready'))::int AS queued_or_ready,
       count(*) FILTER (WHERE status = 'in_progress')::int AS in_progress,
       count(*) FILTER (WHERE status = 'blocked')::int AS blocked,
       count(*) FILTER (WHERE status = 'in_progress' AND updated_at < now() - interval '6 hours')::int AS stale_in_progress_gt_6h,
       (SELECT count(*)::int FROM duplicate_fingerprints) AS duplicate_active_fingerprints,
       min(created_at)::text AS oldest_active_created_at
FROM active;
```

## Verification pattern

- Compile the helper: `python3 -m py_compile /root/.hermes/wolfy/visible_progress_ledger.py`.
- Run Markdown smoke: `python3 /root/.hermes/wolfy/visible_progress_ledger.py --format markdown --limit 2`.
- Run JSON smoke to a temp file and inspect `postgres.backlog_hygiene`.
- Cross-check direct counts: `psql -d wolfy -Atc "select status, count(*) from agent_tasks group by status order by status;"`.

## Safety notes

- Do not mark tasks complete, unblock, requeue, or dedupe during the daily optimizer if allocator/stale-cleanup jobs are due or running.
- This is visibility only: no strategy approval, setup creation, live trading, broker action, schema migration, or cron mutation.
- Preserve the EOD constitution and keep `candidate is not approved` wording in the same visible ledger output.
