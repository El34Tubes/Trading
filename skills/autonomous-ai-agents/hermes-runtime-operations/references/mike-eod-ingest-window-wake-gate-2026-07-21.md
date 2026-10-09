# Mike EOD ingest-window wake gate (2026-07-21)

## Trigger

Use this when Mike's LLM-driven environment triage/repair cron overlaps Wolfy's weekday after-close EOD ingest/signals window and no-agent EOD shard jobs appear to advance `Next run` without fresh `Last run`/session evidence.

## What happened

- Mike autonomous LLM triage started around 16:35 ET while Wolfy EOD price-ingest shards were due at 16:35/16:40/16:45/16:50 ET.
- Cron metadata advanced several shard `Next run` values to the next day, but `Last run` still showed the prior day and there were no matching Hermes `state.db` cron sessions/log lines.
- Manual shard execution proved the wrappers/data path were healthy and wrote fresh Postgres `runs` rows.

## Safe repair pattern

1. Treat the first observation as active-tick/scheduler contention, not immediately as a broken shard wrapper.
2. Verify direct wrapper health with the exact shard wrapper(s):
   ```bash
   python3 /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_2.py
   python3 /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_3.py
   python3 /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_4.py
   python3 /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_5.py
   ```
3. Verify persistence from Postgres `runs` and `prices`, not cron metadata alone:
   ```sql
   select id, job, status, source, started_at, completed_at
   from runs
   where started_at > now() - interval '30 minutes'
   order by id desc;

   select ticker, max(dt) latest_dt, count(*) bars
   from prices
   where ticker in (...shard tickers...)
   group by ticker
   order by ticker;
   ```
4. Add/verify a deterministic wake gate in Mike's triage context so the LLM job yields during the EOD ingest/signals window before collecting expensive context:
   - Weekdays, `16:25` through `17:10` America/New_York.
   - Output final non-empty JSON line:
     ```json
     {"wakeAgent": false, "reason": "eod_ingest_window"}
     ```
   - Keep an emergency override such as `MIKE_TRIAGE_FORCE=1`.
5. Preserve the gate through autorepair/profile sync:
   - Patch canonical `/root/.hermes/scripts/mike_environment_triage_context.py`.
   - Ensure `/root/.hermes/scripts/mike_safe_autorepair.py` syncs it to `/root/.hermes/wolfy/`, Mike profile scripts, and Clerky profile scripts.
   - Run autorepair twice; the second run should be silent.
6. Compile and compare all wrapper copies.

## Verification checklist

- Direct `python3 /root/.hermes/scripts/mike_environment_triage_context.py` during the window prints the skip line plus final JSON gate.
- Unit-style import checks prove in-window true, before/after false, weekend false.
- `cmp -s` confirms global/Wolfy/Mike/Clerky triage wrappers match.
- `python3 -m py_compile` passes for triage and autorepair copies.
- `python3 /root/.hermes/scripts/mike_safe_autorepair.py` is silent on the second run.
- Usage watchdog remains silent; Postgres guard OK; `stale_started_runs=0`; `duplicate_claim_noise=0`.

## Reporting nuance

If manual shard catch-up writes fresh `runs` rows but cron `Last run` still shows the previous day, report the concrete Postgres row IDs and coverage dates. Do not call the shard broken when the direct wrapper and DB persistence are healthy.