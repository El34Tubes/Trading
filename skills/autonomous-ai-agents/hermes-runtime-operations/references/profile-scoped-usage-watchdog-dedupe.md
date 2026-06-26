# Profile-scoped usage watchdog dedupe

Use this when a no-agent usage/quota watchdog repeatedly alerts on already-known LLM usage-limit events or prints the wrong profile's empty usage context.

## Problem pattern

- Production cron jobs live under one profile, commonly `default`.
- The operations/repair job runs under another profile, commonly `mike`.
- A script-only watchdog calls unqualified `hermes insights --days 1`, so it reports the active ops profile instead of the production profile.
- The same day contains many repeated quota/credential-pool log lines. If the watchdog keeps only a small set of seen digests, old digests roll off and the same log lines become "new" again.

## Safe fix

1. Pin usage context to the production profile that owns the jobs:
   ```python
   run(['hermes', '--profile', 'default', 'insights', '--days', '1'])
   ```
2. Increase the retained `seen` digest window enough for noisy days, e.g. from 500 to 5000.
3. Sync the changed wrapper through the script-only autorepair path to relevant profile script directories.
4. Verify with two direct runs:
   ```bash
   python3 /root/.hermes/scripts/wolfy_usage_limit_watchdog.py >/tmp/watchdog_first.out || true
   python3 /root/.hermes/scripts/wolfy_usage_limit_watchdog.py >/tmp/watchdog_second.out || true
   wc -c /tmp/watchdog_first.out /tmp/watchdog_second.out
   ```
   The first run may emit existing newly-detected lines. The second run should be `0` bytes unless genuinely new quota/rate-limit lines appeared between runs.
5. Run the autorepair script twice. The second run should be silent, proving wrapper sync is stable.

## Reporting

Report remaining LLM failures as provider usage-limit / credential-capacity blockers, not as script/runtime breakage, when local tests and no-agent helpers pass.
