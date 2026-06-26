# Wolfy cron tick-lock + visible ledger smoke pattern (2026-06-20)

Context: Mike autonomous environment triage saw default-profile no-agent jobs listed as just due while `hermes --profile default cron status` still reported the old `Next run`. This was not enough evidence to declare the scheduler stuck.

Useful checks:

```bash
hermes --profile default cron status
hermes --profile default cron list --all

# Check both possible lock locations; default-profile cron may still use the global cron dir.
stat /root/.hermes/cron/.tick.lock || true
stat /root/.hermes/profiles/default/cron/.tick.lock || true
ps -p <gateway-pid> -o pid,ppid,stat,etime,cmd
ps -T -p <gateway-pid> | wc -l
```

Observed nuance:

- The relevant lock was `/root/.hermes/cron/.tick.lock`, not `/root/.hermes/profiles/default/cron/.tick.lock`.
- A zero-byte lock with a very recent mtime can simply mean the scheduler tick is active/recent; do not delete it or restart gateway based only on one stale `Next run` line.
- `hermes cron status` can remain stale briefly around just-due no-agent jobs; cross-check `cron list --all`, gateway process health, and logs, then poll once before classifying stuck scheduler.

Visible ledger verification pattern used in the same run:

```bash
python3 -m py_compile /root/.hermes/wolfy/visible_progress_ledger.py /root/.hermes/scripts/mike_safe_autorepair.py
/root/.hermes/scripts/mike_safe_autorepair.py
/root/.hermes/scripts/mike_safe_autorepair.py
/root/.hermes/wolfy/visible_progress_ledger.py --format markdown --limit 5
/root/.hermes/wolfy/visible_progress_ledger.py --format json --limit 3
```

Expected healthy outputs:

- Autorepair emits nothing on repeated runs.
- Ledger Markdown includes snapshot, strategy gates, blockers/noise, next action, and table counts.
- Ledger JSON includes `postgres.historical_depth`, `postgres.strategies`, `cron.active_count`, and `cron.recent_usage_limit_seen`.

Wrapper smoke checks that should stay quiet where expected:

```bash
WOLFY_CONTEXT_SMOKE=1 /root/.hermes/scripts/wolfy_hourly_knowledge_context.py >/tmp/wolfy_hourly_smoke.out
WOLFY_CONTEXT_SMOKE=1 /root/.hermes/scripts/wolfy_clerky_activity_context.py >/tmp/wolfy_clerky_smoke.out
/root/.hermes/scripts/wolfy_usage_limit_watchdog.py >/tmp/wolfy_usage_watchdog.out
/root/.hermes/scripts/wolfy_capture_usage_snapshot.py >/tmp/wolfy_usage_snapshot.out
/root/.hermes/scripts/wolfy_cleanup_stale_agent_coordination.py >/tmp/wolfy_cleanup.out
```

Healthy direct smoke expectations from this run: context scripts produced nonzero deterministic context bytes; usage watchdog, usage snapshot, and stale cleanup produced zero bytes.