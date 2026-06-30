# Wolfy Alpha context smoke: stale standalone `started` rows

When Mike ops is triaging Alpha Search after a provider/model timeout, the safe path is to distinguish three things before changing cron models or alerting:

1. Raw cron config may already have a per-job fallback model (for example `model: gpt-5.4`) while `last_error` still mentions the default model (`gpt-5.5`). Treat that text as stale until verified.
2. Run a direct one-shot smoke with the exact saved profile/model, e.g. `hermes --profile default chat -Q -m gpt-5.4 -q 'Runtime smoke: reply with exactly OK.'`.
3. Run the Alpha context in smoke mode (`WOLFY_CONTEXT_SMOKE=1 python3 /root/.hermes/wolfy/wolfy_alpha_search_context.py`) and verify it produces context.

Pitfall discovered 2026-06-26: prior standalone/manual Alpha context diagnostics can leave `agent_runs.status='started'` rows with no `session_id` and no `cron_job_id` (example note: `Standalone alpha search context loaded.`). If they are clearly stale diagnostic rows, close them as `blocked`, `records_created=0`, with a summary saying no report was fabricated. Do not mark them completed and do not synthesize the missed report.

Post-fix verification used:

```sql
select id, agent_name, status, session_id, cron_job_id, started_at, now()-started_at as age,
       left(coalesce(summary,error_message,''),100) note
from agent_runs
where status='started'
order by started_at;

select count(*) filter (where status='started') as started_runs,
       count(*) filter (where status='started' and started_at < now()-interval '90 minutes') as stale_started_runs
from agent_runs;
```

Expected healthy state during the Mike ops cron: the only `started` row may be the current Mike cron session itself; stale standalone Alpha smoke rows should be gone.