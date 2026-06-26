# Mike cron tick-lock + embedding closure triage (2026-06-25)

Context: Mike's scheduled ops run started while the default-profile cron ticker had just reached a due script-only usage watchdog. `hermes --profile default cron status` and `cron list --all` still showed the 16:15 watchdog as the next run even after 16:15.

Useful pattern:

1. Treat a just-stale `Next run` as a lead, not proof of a stuck scheduler.
2. Check the active tick lock and current LLM cron session:
   - `/root/.hermes/cron/.tick.lock` may be zero-byte and updated at the current LLM ops run start.
   - `agent.log` can show the active `cron_<job_id>_<timestamp>` session still consuming the scheduler tick.
3. If the active LLM cron run is the ops run itself, do not report the due no-agent job as stuck; the tick will advance after the active run exits or the next poll.
4. Cross-check health with direct script smokes where safe. In this session, direct double-run of `wolfy_usage_limit_watchdog.py` was silent, confirming no active usage-limit alert even though the scheduled timestamp had not advanced yet.
5. For embedding drift, run the safe autorepair/embedding sync path and verify the exact invariant:
   - `select count(*) total, count(embedding) embedded, count(*)-count(embedding) missing from knowledge_chunks;`
   - Report only if missing remains nonzero or the sync emits actionable output.

Pitfall: don't convert historical Jonah ad-hoc tool warnings or a stale displayed `Next run` during an active LLM cron tick into a user-facing incident when direct smokes and Postgres invariants are clean.