# Mike clean ops: stale due cron timestamps with no actionable state (2026-07-09)

Use this as a compact pattern for scheduled Mike/Wolfy environment-triage runs when injected context shows jobs just due or slightly stale but the deterministic health surface is otherwise clean.

## Observed shape

- `hermes --profile default cron list --all` showed several script-only jobs with `Next run` timestamps a few minutes in the past.
- `hermes --profile default cron status` reported the gateway running and still showed the same stale next-run timestamp.
- Gateway process was alive, but log searches for the just-due cron session names/timestamps returned no fresh entries.
- Direct script smokes were clean/silent:
  - `mike_safe_autorepair.py` twice: 0 bytes output both runs.
  - `wolfy_usage_limit_watchdog.py` twice: 0 bytes output both runs.
  - `wolfy_cleanup_stale_agent_coordination.py`: 0 bytes output.
  - `wolfy_embed_knowledge_chunks.py`: 0 bytes output.
- Postgres guard and coordination invariants were clean:
  - Postgres 16/pgvector requirements OK.
  - `stale_started_runs=0`.
  - no synthetic smoke blockers.
  - no fresh `duplicate-or-already-claimed` noise.
- Wrapper/script preservation was already healthy:
  - global/Wolfy/Mike/Clerky copies for `wolfy_tiered_backfill_bounded.py` and `wolfy_eod_weekly_research_context.py` existed and compiled.
  - bounded backfill `--help` worked from all wrapper layers.
  - weekly research budget-gate smoke emitted final JSON `{"wakeAgent": false, "reason": "budget"}`.

## Operating rule

Do not report a stale scheduler incident solely because `cron list/status` shows a just-due script-only job in the past when all direct smokes and ledger invariants are clean. Treat it as unresolved/active-tick scheduler observation unless it persists across a later poll and correlates with failed direct smokes, missing wrappers, stuck processes, a stale tick lock that blocks jobs, or new ledger/log noise.

For scheduled Mike ops jobs with no safe fix applied and no remaining actionable blocker, final output should be exactly:

```text
[SILENT]
```

## Useful verification commands

```bash
python3 /root/.hermes/wolfy/check_postgres_requirements.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py > /tmp/auto1.txt && python3 /root/.hermes/scripts/mike_safe_autorepair.py > /tmp/auto2.txt && wc -c /tmp/auto1.txt /tmp/auto2.txt
python3 /root/.hermes/scripts/wolfy_usage_limit_watchdog.py > /tmp/usage1.txt; python3 /root/.hermes/scripts/wolfy_usage_limit_watchdog.py > /tmp/usage2.txt; wc -c /tmp/usage1.txt /tmp/usage2.txt
python3 /root/.hermes/scripts/wolfy_cleanup_stale_agent_coordination.py > /tmp/cleanup.txt; wc -c /tmp/cleanup.txt
python3 /root/.hermes/scripts/wolfy_embed_knowledge_chunks.py > /tmp/embed.txt; wc -c /tmp/embed.txt
psql -d wolfy -c "select count(*) filter (where status='started' and started_at < now()-interval '30 minutes') as stale_started_runs, count(*) filter (where status='blocked' and title ilike '%Smoke blocked task%') as synthetic_blocked_tasks from agent_tasks;" -c "select count(*) as duplicate_claim_noise from agent_runs where status='blocked' and error_message='duplicate-or-already-claimed' and started_at > now()-interval '24 hours';"
WOLFY_CONTEXT_SMOKE=1 python3 /root/.hermes/scripts/wolfy_eod_weekly_research_context.py
python3 /root/.hermes/scripts/wolfy_tiered_backfill_bounded.py --help
hermes --profile default cron list --all
hermes --profile default cron status
```

Avoid turning stale historical tool-error tails into a report if the exact live wrappers now exist/compile and the current no-agent helpers are silent.