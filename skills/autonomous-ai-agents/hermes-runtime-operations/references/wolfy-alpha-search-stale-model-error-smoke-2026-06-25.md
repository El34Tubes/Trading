# Wolfy Alpha Search stale model error smoke (2026-06-25)

## Trigger

A scheduled Mike operations run saw the default-profile `Wolfy separate Alpha Search Report` cron job showing a prior `last_error`:

- `Non-streaming API call timed out after 90s`
- Error text said Codex appeared to reject `gpt-5.5`
- The same cron job's saved config already had `model: gpt-5.4`

This is a stale/contradictory-error case: the error text may reflect startup/default model wording even when the job has an explicit fallback model configured.

## Safe triage pattern

1. Inspect the production profile cron entry, not just the active ops profile:
   ```bash
   hermes --profile default cron list --all
   ```

2. If needed, inspect the raw job record for `model`, `provider`, `base_url`, `last_error`, and `next_run_at`:
   ```bash
   # Prefer read_file/search tools in-agent; shell shown for manual ops only.
   python3 - <<'PY'
   import json
   p='/root/.hermes/cron/jobs.json'
   data=json.load(open(p))
   for j in data['jobs']:
       if j['id']=='4452bdae4553':
           print({k:j.get(k) for k in ['id','name','model','provider','base_url','last_status','last_error','next_run_at']})
   PY
   ```

3. Smoke the exact configured fallback model with the production profile before changing cron config:
   ```bash
   hermes --profile default chat -Q -m gpt-5.4 -q 'Runtime smoke: reply with exactly OK.'
   ```

4. Smoke the deterministic context script without opening a run row:
   ```bash
   WOLFY_CONTEXT_SMOKE=1 python3 /root/.hermes/wolfy/alpha_search_context.py
   ```

5. Confirm no active ledger damage:
   ```sql
   select count(*) from agent_runs where status='started';
   select count(*) from agent_runs
     where error_message='duplicate-or-already-claimed'
       and started_at > now()-interval '2 hours';
   ```

6. Run the quiet watchdog/autorepair checks twice where relevant:
   ```bash
   python3 /root/.hermes/scripts/wolfy_usage_limit_watchdog.py
   python3 /root/.hermes/scripts/wolfy_usage_limit_watchdog.py
   python3 /root/.hermes/scripts/mike_safe_autorepair.py
   python3 /root/.hermes/scripts/mike_safe_autorepair.py
   ```

## Decision rule

If the cron job is already configured for the fallback model, direct `hermes --profile default chat -Q -m <model>` returns `OK`, context smoke works, usage watchdog is silent, and coordination counts are clean, do **not** edit the cron job or alert the user. Let the next scheduled retry run normally. For scheduled Mike ops, return exactly `[SILENT]` when nothing else is actionable.

Only intervene if the direct model smoke fails, a stale `agent_runs.status='started'` row remains after the timeout window, or watchdog/logs show an active provider quota/rate-limit event.
