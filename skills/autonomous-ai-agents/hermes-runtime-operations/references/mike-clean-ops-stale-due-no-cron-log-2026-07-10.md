# Mike clean ops: stale just-due cron timestamp with no cron log lines (2026-07-10)

Context: Mike autonomous environment triage ran at 03:58 ET, with several default-profile jobs due at 04:00. `hermes --profile default cron status` and `cron list --all` still showed `Next run: 2026-07-10T04:00:00-04:00` at 04:02.

Safe interpretation pattern:

1. Do not immediately declare the scheduler stuck from `cron status` alone.
2. Check the current Mike ops run in Postgres `agent_runs`; a fresh `status='started'` row for `cron:fdfd5b53b5d5` is expected until the running ops turn finishes and is not stale coordination noise.
3. Check tick lock mtime in both possible places:
   - `/root/.hermes/cron/.tick.lock`
   - `/root/.hermes/profiles/default/cron/.tick.lock`
   A zero-byte global lock recently touched by the current ops run is a lead, not proof of failure.
4. If gateway logs around the due minute show only housekeeping/session-expiry and no explicit cron job start lines, treat it as unresolved scheduler triage unless it persists after the active LLM cron run exits.
5. Before changing cron/gateway state, run direct no-agent smokes for the due script-only jobs when safe. In this run, the usage watchdog twice, embedding sync, stale cleanup, usage snapshot, Postgres guard, and autorepair twice were all clean/silent.
6. Rerun exact scratch probes from recent error tails before adding schema aliases. The XBI scratch probe that had earlier failed on `scanner_results.metadata` exited 0 later because the compatibility alias already existed.
7. If all live invariants are clean and no new fix/blocker remains, final response for the scheduled Mike ops pass should be exactly `[SILENT]`.

Verification commands used:

```bash
/root/.hermes/wolfy/check_postgres_requirements.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py >/tmp/mike_autorepair_1.out 2>/tmp/mike_autorepair_1.err
python3 /root/.hermes/scripts/mike_safe_autorepair.py >/tmp/mike_autorepair_2.out 2>/tmp/mike_autorepair_2.err
python3 /root/.hermes/scripts/wolfy_usage_limit_watchdog.py >/tmp/wolfy_usage_watchdog_1.out 2>/tmp/wolfy_usage_watchdog_1.err
python3 /root/.hermes/scripts/wolfy_usage_limit_watchdog.py >/tmp/wolfy_usage_watchdog_2.out 2>/tmp/wolfy_usage_watchdog_2.err
python3 /root/.hermes/scripts/wolfy_embed_knowledge_chunks.py >/tmp/wolfy_embed_smoke.out 2>/tmp/wolfy_embed_smoke.err
python3 /root/.hermes/wolfy/tmp_xbi_3454_query.py >/tmp/tmp_xbi_3454.out 2>/tmp/tmp_xbi_3454.err
psql -d wolfy -c "select id,agent_name,status,job_id,session_id,started_at,now()-started_at as age,left(coalesce(summary,''),80) summary from agent_runs where status='started' order by started_at desc limit 10;"
stat -c '%n size=%s mtime=%y' /root/.hermes/cron/.tick.lock /root/.hermes/profiles/default/cron/.tick.lock 2>/dev/null || true
```
