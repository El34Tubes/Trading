# Wolfy usage-limit stale Jonah run requeue — 2026-07-02

## Trigger
A transient OpenAI Codex `usage_limit_reached` / HTTP 429 window left Jonah coordination rows open:

- `agent_runs.status='started'` with `records_created=0` or no durable artifact
- linked `agent_tasks.status='in_progress'`
- later Jonah runs were succeeding again and the dedicated usage-limit watchdog ran silently twice

This is not a market-analysis failure and should not fabricate missed research output.

## Safe repair pattern
1. Verify the stuck rows and confirm they are not the currently-running Mike ops cron session:
   ```sql
   select id, agent_name, status, task_id, started_at, now()-started_at as age,
          left(coalesce(error_message, summary,''),160) as note
   from agent_runs
   where status='started'
   order by started_at desc;

   select id, title, status, agent, updated_at, now()-updated_at as age,
          left(coalesce(error_message, description,''),160) as note
   from agent_tasks
   where status='in_progress'
   order by updated_at desc;
   ```
2. If the linked run died before producing an artifact and the task is safe to retry, close the stale run as blocked with `records_created=0` and requeue the linked task:
   ```sql
   begin;
   update agent_runs
   set status='blocked', ended_at=now(), records_created=0,
       error_message='usage-limit/startup failure left run open before research output; task requeued by ops',
       summary='Blocked stale started run from transient usage-limit window; no output fabricated; linked task requeued for retry.'
   where id in (<run_ids>) and status='started'
   returning id, task_id, status, records_created;

   update agent_tasks
   set status='queued', claim_token=null, claimed_at=null, updated_at=now(),
       error_message=null,
       summary=concat_ws(E'\n', summary, 'Requeued by ops after linked run hit transient usage-limit/startup failure before output.')
   where id in (<task_ids>) and status='in_progress'
   returning id, title, status, claimed_at;
   commit;
   ```
3. Run the dedicated usage-limit watchdog twice. If it is silent and later LLM cron jobs are succeeding, treat the 429 as a resolved transient event rather than pausing jobs.
4. Run stale cleanup, embedding sync, usage snapshot, and safe autorepair smokes. Interpret aggregate usage threshold output as a volume warning, not an active outage, unless the usage-limit watchdog/logs show a current limit.
5. Verify:
   ```sql
   select count(*) as non_mike_started_runs
   from agent_runs
   where status='started'
     and not (agent_name='Mike' and cron_job_id='<current_mike_ops_job_id>');

   select count(*) as in_progress_tasks from agent_tasks where status='in_progress';
   select count(*) as duplicate_claim_noise
   from agent_runs
   where error_message='duplicate-or-already-claimed'
     and started_at > now() - interval '24 hours';
   select count(*) total_chunks, count(embedding) embedded_chunks from knowledge_chunks;
   ```

## Reporting
Report the repair as coordination cleanup, not market analysis. If the usage snapshot emits a high-token warning while the usage watchdog is silent, say it is a usage-volume warning and that no jobs were paused.