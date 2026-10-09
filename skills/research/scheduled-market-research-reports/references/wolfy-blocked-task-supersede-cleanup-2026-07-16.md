# Wolfy blocked-task supersede cleanup — 2026-07-16

Use this pattern when the user asks to clear Wolfy blocked tasks and the visible ledger/DB shows stale `agent_tasks.status='blocked'` rows.

## Key distinction

- **Active blockers:** rows in Postgres `agent_tasks` with `status='blocked'`. These affect backlog hygiene and should be resolved or explicitly superseded.
- **Historical noise:** rows in `agent_runs` with `status='blocked'` can still appear under the visible ledger's “Blockers / noise” section after active tasks are clean. Do not treat old `agent_runs` rows as active blocked work.

## Audit queries

```sql
select status, count(*)
from agent_tasks
group by status
order by status;

select id, agent_name, status,
       left(coalesce(title, task_type, ''), 80) as title,
       left(coalesce(blocker_reason, ''), 220) as blocker_reason,
       created_at, updated_at
from agent_tasks
where status='blocked'
order by updated_at desc nulls last;
```

For stale scanner-alpha research blockers, check whether later Jonah work superseded the task:

```sql
with b as (
  select id, title, ticker_symbols[1] ticker, created_at
  from agent_tasks
  where status='blocked' and agent_name='Jonah'
)
select b.id, b.ticker, left(b.title,45) title,
       count(a.id) filter (where a.created_at > b.created_at) later_artifacts,
       max(a.created_at) filter (where a.created_at > b.created_at) latest_artifact
from b
left join agent_artifacts a
  on a.agent_name='Jonah'
 and a.ticker_symbols @> array[b.ticker]::text[]
group by b.id, b.ticker, b.title
order by b.id;
```

For Sentinel review blockers, verify whether review work is still needed:

```sql
select status, count(*)
from recommendations
group by status
order by status;
```

If `pending=0`, an old “review pending recommendations” task is usually obsolete.

## Supersede/complete pattern

When blocked tasks are stale, user explicitly asks to clear/supersede, and verification shows they are no longer active work:

1. Update only the intended task IDs.
2. Set `status='completed'`, `completed_at=now()`, `updated_at=now()`.
3. Clear `error_message` and `blocker_reason`.
4. Preserve why it was closed in `summary` and `payload.cleanup_*` fields.
5. Verify `agent_tasks` blocked count is zero.

Example shape:

```sql
begin;
with targets as (
  select id,
         case
           when id = <sentinel_id> then 'Superseded/obsolete cleanup: old Sentinel review task; current recommendations have no pending rows, so no review work is required.'
           else 'Superseded cleanup: old Jonah scanner-alpha research task went stale after provider/startup/token interruption; later Jonah artifact(s) exist for this ticker, so this blocked task is no longer needed.'
         end as cleanup_summary
  from agent_tasks
  where id in (<ids>) and status='blocked'
)
update agent_tasks t
set status='completed',
    completed_at=now(),
    updated_at=now(),
    summary=targets.cleanup_summary,
    error_message=null,
    blocker_reason=null,
    payload=coalesce(t.payload, '{}'::jsonb) || jsonb_build_object(
      'cleanup_action','superseded_blocked_task_cleanup',
      'cleanup_at',now(),
      'cleanup_reason',targets.cleanup_summary
    )
from targets
where t.id=targets.id
returning t.id, t.agent_name, t.status, t.summary;
commit;
```

## Reporting shape

Report a compact table:

- blocked before/after
- tasks superseded/completed
- queued remaining
- in-progress count
- cron active/paused if relevant

Add the nuance: the visible ledger may still show old historical `agent_runs` blocker/noise rows; that does not mean active `agent_tasks` are still blocked.