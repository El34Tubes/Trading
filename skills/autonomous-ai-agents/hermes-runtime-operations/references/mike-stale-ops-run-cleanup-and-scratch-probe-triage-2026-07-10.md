# Mike stale ops run cleanup + scratch probe triage (2026-07-10)

Use when a scheduled Mike/Hermes runtime-ops pass sees one `agent_runs.status='started'` row or recent log tails that mention ad-hoc `tmp_*.py` probe failures.

## Pattern

1. Treat recent log tails as leads, not truth.
   - Rerun the exact scratch probe before editing schema or code.
   - If the probe now exits 0, classify the log line as stale/resolved and make no compatibility migration.

2. Inspect started rows directly:
   ```bash
   psql -d wolfy -P pager=off -c "select id,agent_name,status,source,cron_job_id,session_id,started_at,now()-started_at as age,title,error_message from agent_runs where status='started' order by started_at desc limit 5;"
   ```

3. Distinguish the current Mike cron session from stale prior Mike sessions.
   - A fresh row for the currently running Mike ops cron session is expected and should not be closed.
   - A prior Mike ops cron row left open for ~90+ minutes after a timeout/tool failure can be closed as `blocked` with `records_created=0`.

4. Close only the stale prior row, never fabricate the missed report/artifact:
   ```bash
   python3 /root/.hermes/wolfy/wolfy_agent_cli.py run-finish \
     --run-id <RUN_ID> \
     --status blocked \
     --records-created 0 \
     --summary 'Closed stale Mike autonomous environment repair cron session; previous run exceeded expected window/tool timeout before it could finish its agent_runs row. No user artifact fabricated.' \
     --error-message 'stale Mike ops cron run cleanup: prior session left agent_runs.status=started; closed as blocked records_created=0'
   ```

5. Verify after cleanup:
   ```bash
   /root/.hermes/wolfy/check_postgres_requirements.py
   python3 /root/.hermes/scripts/mike_safe_autorepair.py
   python3 /root/.hermes/scripts/mike_safe_autorepair.py
   python3 /root/.hermes/scripts/wolfy_usage_limit_watchdog.py
   python3 /root/.hermes/scripts/wolfy_usage_limit_watchdog.py
   python3 /root/.hermes/scripts/wolfy_cleanup_stale_agent_coordination.py
   python3 /root/.hermes/scripts/wolfy_embed_knowledge_chunks.py
   psql -d wolfy -P pager=off -c "select count(*) as stale_started_runs from agent_runs where status='started' and started_at < now() - interval '90 minutes'; select count(*) as duplicate_claim_noise from agent_runs where error_message='duplicate-or-already-claimed' and started_at > now() - interval '24 hours'; select count(*) total_chunks,count(embedding) embedded_chunks from knowledge_chunks;"
   hermes --profile default cron status
   ```

## Reporting

If all verification is clean, report the stale row closure as the fix, list concrete verification outputs, and note that optional credential/tool warnings are setup gaps rather than runtime breakage. Do not report stale scratch-probe errors as active blockers when the exact rerun succeeds.
