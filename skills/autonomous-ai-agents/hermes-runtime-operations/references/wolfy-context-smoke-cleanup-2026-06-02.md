# Wolfy context-script smoke cleanup (2026-06-02)

When Mike smoke-tests Wolfy cron context scripts directly, several scripts intentionally create coordination ledger rows as part of normal context generation:

- `wolfy_report_context.py` starts a `agent_runs` row for `Wolfy / analyst_recommender`.
- `wolfy_hourly_knowledge_context.py` may claim a queued `agent_tasks` row and start a `Jonah / research` run.
- `wolfy_alpha_search_context.py` starts a `Wolfy / alpha_scout` run.
- `wolfy_clerky_activity_context.py` reports these rows in the administrative ledger context.

Safe smoke-test pattern:

1. Run the context scripts and capture stdout/stderr/exit code.
2. Query Postgres for temporary `started` rows:
   ```bash
   psql -d wolfy -P pager=off -c "select id,agent_name,role,job_id,task_id,started_at,summary from agent_runs where status='started' order by started_at desc limit 10;"
   ```
3. Close smoke-created runs explicitly with zero writes, e.g.:
   ```bash
   python3 /root/.hermes/wolfy/wolfy_agent_cli.py run-finish --run-id <wolfy_report_run> --status completed --records-created 0 --summary 'Mike smoke-test report context invocation completed without DB writes'
   python3 /root/.hermes/wolfy/wolfy_agent_cli.py complete --task-id <jonah_task> --run-id <jonah_run> --records-created 0 --summary 'Mike smoke-test Jonah context invocation completed without DB writes'
   python3 /root/.hermes/wolfy/wolfy_agent_cli.py run-finish --run-id <alpha_run> --status completed --records-created 0 --summary 'Mike smoke-test alpha context invocation completed without DB writes'
   ```
4. Verify no `started` / `in_progress` smoke noise remains:
   ```bash
   psql -d wolfy -Atc "select status,count(*) from agent_runs group by status order by status; select status,count(*) from agent_tasks group by status order by status;"
   ```
5. When commenting on Kanban, mention that smoke-created rows were closed with `records_created=0` so future agents do not mistake them for stale production work.

Pitfall: do not treat the row creation itself as a bug; it is how the context scripts hand off run-finish instructions to the real agent jobs. The operational requirement is to clean up rows created by manual smoke invocations.