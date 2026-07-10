# Wolfy usage watchdog stale 429 log trim (2026-07-09)

## When to use

Use this when the user asks to trim/clean stale 429 or provider usage-limit logs because Wolfy's usage-limit watchdog is seeing old quota evidence, or when active logs contain large volumes of historical `HTTP 429` / `usage_limit_reached` lines that can confuse recency-based scans.

## Safe pattern

1. Back up every log before editing.
   - Example backup directory shape: `/root/.hermes/logs/backup-before-stale-429-trim-YYYY-MM-DD/`.
2. Remove only stale quota/provider-limit evidence, not arbitrary errors.
   - Good match terms: `usage_limit_reached`, `usage limit has been reached`, `HTTP 429`, `Error code: 429`, `status 429`, `too many requests`, `quota exceeded`, `daily limit`.
   - Treat dated lines older than today as stale.
   - Also remove undated traceback/detail continuation lines matching the same quota pattern; otherwise they may look fresh to watchdog logic that accepts undated lines.
   - Do not remove today's active quota lines unless the user explicitly wants a full scrub; today's lines are useful for active gating.
3. Run the usage-limit watchdog immediately after trimming.
   - For Wolfy/default profile: `python3 /root/.hermes/scripts/wolfy_usage_limit_watchdog.py`.
   - Healthy result after a stale-log trim is exit code 0 and empty stdout.
4. Verify the tail window is clean.
   - Check the last scanner window (currently the watchdog reads the last 3000 lines per active log) for remaining quota hits in `/root/.hermes/logs/*.log` and `/root/.hermes/cron.log` if present.
5. Report counts and backup path concisely.

## Concrete result from the session

A manual trim removed stale provider-limit lines from:

- `/root/.hermes/logs/gateway.log`: 4 removed
- `/root/.hermes/logs/errors.log`: 3,408 removed
- `/root/.hermes/logs/agent.log`: 2,517 removed

Backup path: `/root/.hermes/logs/backup-before-stale-429-trim-2026-07-09/`.

Verification:

- Watchdog exit code: 0
- Watchdog stdout: empty
- Quota hits in the last 3000 lines of active logs: 0

## Pitfalls

- Do not search for bare `429` as the cleanup predicate: memory/GC numbers, timestamps, and user chat text may contain 429 without being provider quota evidence.
- Do not rewrite or truncate entire logs unless explicitly asked; targeted line removal plus backup is safer.
- Do not treat old `last_error` or historical log tails as current quota truth. Run the watchdog after cleanup and verify the current tail window.