# Mike clean ops when optimizer is budget-blocked and usage snapshot is noisy (2026-07-13)

## Trigger

A scheduled Mike autonomous environment triage run saw:

- `wolfy_capture_usage_snapshot.py` printed a high cron-token threshold line.
- The dedicated `wolfy_usage_limit_watchdog.py` ran twice with exit 0 and empty stdout/stderr.
- `budget_gate.py --no-record` returned `BUDGET=block token_cap_exceeded ...` for the daily optimizer.
- The prior optimizer cron session had already completed successfully as plan-only, persisted a queued next task, and reported the budget block.
- Recent logs contained historical tool warnings from the prior optimizer run, including a missing `probation.json` read and a psycopg `%optimization%` placeholder mistake, but the optimizer final response was successful and no durable source contained that bad query.

## Correct handling

Treat this as a clean/silent ops pass if live invariants are healthy:

1. Do not report the aggregate usage snapshot threshold as an active quota incident when the dedicated usage watchdog is silent twice and scoped auth is healthy.
2. Do not re-alert on a budget block that the optimizer already handled in its own final report, unless it leaves stale rows, paused jobs, or failed wake-gates.
3. Do not patch code/prompts for historical ad-hoc tool warnings when the owning cron session completed and there is no durable script/prompt containing the failing query.
4. Verify current invariants instead:
   - Postgres requirements guard OK.
   - Default and Mike cron listings sane; gateway cron status running.
   - `mike_safe_autorepair.py` twice silent.
   - `wolfy_usage_limit_watchdog.py` twice silent.
   - `wolfy_cleanup_stale_agent_coordination.py` silent.
   - `stale_started_runs=0` excluding the current Mike ops run.
   - `duplicate_claim_noise=0`.
   - embeddings complete (`count(*) == count(embedding)`).
   - config guardian OK with explicit `--home /root/.hermes`.
5. If nothing changed and no blocker remains, return exactly `[SILENT]`.

## Useful commands

```bash
python3 /root/.hermes/wolfy/check_postgres_requirements.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py >/tmp/autorepair1.out 2>/tmp/autorepair1.err
python3 /root/.hermes/scripts/mike_safe_autorepair.py >/tmp/autorepair2.out 2>/tmp/autorepair2.err
python3 /root/.hermes/scripts/wolfy_usage_limit_watchdog.py >/tmp/usage1.out 2>/tmp/usage1.err
python3 /root/.hermes/scripts/wolfy_usage_limit_watchdog.py >/tmp/usage2.out 2>/tmp/usage2.err
python3 /root/.hermes/scripts/wolfy_cleanup_stale_agent_coordination.py >/tmp/cleanup.out 2>/tmp/cleanup.err
python3 /root/.hermes/wolfy/guardian/config_guardian.py --home /root/.hermes --skip-cli
python3 /root/.hermes/wolfy/guardian/budget_gate.py --no-record
hermes cron status
hermes --profile default cron list --all
hermes --profile mike cron list --all
psql -d wolfy -P pager=off -c "select count(*) from agent_runs where status='started' and started_at < now() - interval '45 minutes';"
psql -d wolfy -P pager=off -c "select count(*) from agent_runs where error_message='duplicate-or-already-claimed' and started_at > now() - interval '8 hours';"
psql -d wolfy -P pager=off -c "select count(*) total, count(embedding) embedded from knowledge_chunks;"
```

## Pitfalls

- A current Mike ops `agent_runs.status='started'` row is expected while the cron session is still running. Do not close it as stale.
- `wolfy_capture_usage_snapshot.py` is an aggregate volume alarm, not the quota gate. Use the dedicated usage watchdog and provider evidence to decide whether to alert or pause jobs.
- A `budget_gate` block can be an expected optimizer throttle, not an ops incident, if the optimizer records a plan-only run/task and exits OK.
