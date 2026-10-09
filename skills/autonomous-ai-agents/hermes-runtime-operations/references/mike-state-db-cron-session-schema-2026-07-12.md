# Mike state.db cron session schema pitfall (2026-07-12)

During Mike/Wolfy cron triage, a direct SQLite probe failed because it assumed web/API-style column names in `~/.hermes/state.db.sessions`:

```sql
select session_id, source, created_at, updated_at from sessions ...
-- fails: no such column: session_id
```

The live Hermes session table uses:

- `id` — session id, including cron ids like `cron_<job_id>_<timestamp>`
- `source` — e.g. `cron`
- `started_at` / `ended_at` — REAL unix timestamps
- no `session_id`, `created_at`, or `updated_at` columns

Use this pattern when checking whether a cron job actually created a session:

```bash
sqlite3 /root/.hermes/state.db "
select id,
       source,
       datetime(started_at,'unixepoch','localtime') as started_local,
       datetime(ended_at,'unixepoch','localtime') as ended_local,
       end_reason,
       message_count
from sessions
where id like 'cron_%'
  and started_at > strftime('%s','now','-20 minutes')
order by started_at desc
limit 20;
"
```

Related Postgres coordination nuance: `agent_runs` may also not have a generic `created_at` column in this deployment. For stale-run checks, inspect columns first or use `started_at`/`ended_at` directly:

```sql
select column_name
from information_schema.columns
where table_name='agent_runs'
  and column_name in ('started_at','created_at','ended_at','status','session_id','cron_job_id');

select count(*) filter (
  where status='started' and started_at < now() - interval '2 hours'
) as stale_started_runs
from agent_runs;
```

Operational interpretation from the same run:

- A current Mike ops LLM cron session can hold the active tick while just-due no-agent jobs appear delayed or have advanced `Next run` without a fresh `Last run` yet.
- Validate direct script smokes, tick-lock freshness, `agent.log` cron.scheduler lines, and the current `cron_<job_id>...` session before declaring the scheduler stuck.
- If all smokes are silent/clean and no state changed, return exact `[SILENT]` for scheduled Mike ops.