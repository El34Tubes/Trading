# Wolfy Alpha Search timeout stale-run cleanup — 2026-06-25

## Trigger

Mike ops triage found the default-profile `Wolfy separate Alpha Search Report` cron job had failed with a Codex non-streaming timeout before the LLM could persist the report or finish its Postgres `agent_runs` row. The pre-run context had opened `agent_runs.id=157717` with `status='started'`, leaving stale coordination noise.

## Safe repair pattern

1. Inspect the stale started rows and identify the exact cron/context run:
   ```bash
   psql -d wolfy -P pager=off -c "select id, agent_name, status, source, cron_job_id, session_id, started_at, now()-started_at as age, left(coalesce(summary,error_message,''),160) as note from agent_runs where status='started' order by started_at desc;"
   ```
2. Inspect the cron job config before editing. Historical `last_error` text may mention the default/startup model even when the saved per-job model has already been changed to a fallback such as `gpt-5.4`.
3. If the LLM failed before persistence/finalization, close only the stale DB run as blocked; do **not** fabricate a missed market report and do **not** mark it completed:
   ```bash
   python3 /root/.hermes/wolfy/wolfy_agent_cli.py run-finish \
     --run-id <RUN_ID> \
     --status blocked \
     --records-created 0 \
     --error-message "<specific timeout/config blocker>" \
     --summary "Closed stale cron run after provider timeout; no records created by failed LLM run."
   ```
4. Verify the cleanup and the next scheduled retry separately:
   ```bash
   psql -d wolfy -P pager=off -c "select count(*) as stale_started_runs from agent_runs where status='started' and started_at < now() - interval '90 minutes';"
   hermes --profile default cron list --all
   ```
5. Run script-only health checks that should remain silent on success:
   ```bash
   python3 /root/.hermes/scripts/mike_safe_autorepair.py >/tmp/mike_autorepair_1.out
   python3 /root/.hermes/scripts/mike_safe_autorepair.py >/tmp/mike_autorepair_2.out
   python3 /root/.hermes/wolfy/wolfy_cleanup_stale_agent_coordination.py >/tmp/stale_cleanup.out
   python3 /root/.hermes/wolfy/wolfy_embed_knowledge_chunks.py >/tmp/embed_sync.out
   ```

## Verification from the session

- Closed run `157717` as `blocked` with `records_created=0`.
- Verified stale started runs older than 90 minutes dropped to `0`.
- Verified no fresh `duplicate-or-already-claimed` noise.
- Ran safe autorepair twice; both runs silent.
- Ran stale coordination cleanup and embedding sync; both silent.
- Embedding sync also closed a separate benign gap: `knowledge_chunks` became `906 total / 906 embedded / 0 missing`.
- Confirmed Alpha Search cron remained active for the next scheduled run and was already configured with `model: gpt-5.4`, so no immediate model edit was made from stale error text alone.

## Reporting rule

Report this as an operations cleanup, not a market-analysis result: the failed Alpha Search report was not generated, the stale ledger row was safely closed, and the next cron retry remains scheduled.