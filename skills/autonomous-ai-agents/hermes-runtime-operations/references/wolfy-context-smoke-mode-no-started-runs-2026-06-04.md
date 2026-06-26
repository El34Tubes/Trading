# Wolfy context smoke mode without `started` run noise (2026-06-04)

## Trigger

Use this when an operations pass needs to smoke-test a Wolfy context generator that normally starts a Postgres `agent_runs` row for the downstream LLM to finish. Manual probes can leave `status='started'` rows that look like stale production work.

## Pattern

1. Add an environment-gated smoke mode to the context helper:
   ```python
   import os

   smoke_mode = os.getenv('WOLFY_CONTEXT_SMOKE') == '1'
   run_id = None
   if not smoke_mode:
       with connect(PG_DSN) as conn:
           run_id = start_agent_run(..., status='started', ...)

   if run_id is None:
       print('Postgres agent run: skipped because WOLFY_CONTEXT_SMOKE=1')
       print('Smoke mode only: no agent_runs row was opened.')
   else:
       print(f'Postgres agent run: AGENT_RUN_ID={run_id}')
       print(f'After writes, run: python3 {CLI} run-finish --run-id {run_id} ...')
   ```

2. Verify the smoke mode does not create ledger noise:
   ```bash
   before=$(psql -d wolfy -At -c "select count(*) from agent_runs where status='started'")
   WOLFY_CONTEXT_SMOKE=1 python alpha_search_context.py >/tmp/context_smoke.out
   after=$(psql -d wolfy -At -c "select count(*) from agent_runs where status='started'")
   grep -E 'skipped because WOLFY_CONTEXT_SMOKE|Smoke mode only' /tmp/context_smoke.out
   printf 'started_before=%s started_after=%s\n' "$before" "$after"
   ```

3. If manual probes already left stale context-only rows, close them explicitly, not silently:
   ```bash
   python wolfy_agent_cli.py run-finish \
     --run-id <id> \
     --status completed \
     --records-created 0 \
     --summary 'operations smoke cleanup: context-only row left open by manual/test smoke; no market records created'
   ```

4. Re-run the relevant regression and smoke tests, then verify `agent_runs` has no unwanted `started` rows.

## Notes

- This is for deterministic operations smoke tests only. Real cron contexts should still open run rows so downstream agents can close them after writing durable artifacts.
- Use this pattern instead of avoiding context smoke tests; the goal is to keep verification strong without polluting coordination ledgers.
- This specific fix was applied to `/root/.hermes/wolfy/alpha_search_context.py` after an operations smoke left Alpha Search/Wolfy context-only rows open. Verification used `started_before=0 started_after=0` and the local Wolfy smoke suite passed.