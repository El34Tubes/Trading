# Mike silent ops clean-health check — 2026-07-07 22:22 ET

Use this as a compact example of a healthy Mike autonomous environment triage run that should suppress delivery with exactly `[SILENT]`.

## Context

The injected pre-run context showed:

- Active profile: `mike`; production Wolfy jobs live under `default`.
- Default-profile cron had 27 active jobs, including Mike ops, script-only watchdogs, EOD shards, tiered backfill, and config guardian.
- Hermes doctor only had expected credential/tool-configuration warnings; no installable dependency failures.
- Postgres guard passed on PostgreSQL 16.14 with `pg_trgm` and `vector` present.
- Coordination smoke counts were clean: `stale_started_runs=0`, `synthetic_blocked_tasks=0`, `duplicate_claim_noise=0`.
- Embedding sync, stale cleanup, and usage snapshot helpers were silent.
- Recent error tails contained historical Jonah scratch-query warnings and one earlier mistaken `bash` invocation of a Python watchdog, but live smokes were clean.

## Verification pattern used

Run safe, direct checks only; do not mutate DB state or force cron when the active LLM ops job is running.

```bash
python3 /root/.hermes/wolfy/check_postgres_requirements.py
hermes --profile default cron list --all

python3 /root/.hermes/scripts/wolfy_usage_limit_watchdog.py
/root/.hermes/scripts/wolfy_usage_limit_watchdog.py

python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py

psql -d wolfy \
  -c "select count(*) as stale_started_runs from agent_runs where status='started' and started_at < now() - interval '2 hours';" \
  -c "select count(*) as duplicate_claim_noise from agent_runs where error_message='duplicate-or-already-claimed' and started_at > now() - interval '24 hours';" \
  -c "select count(*) as synthetic_blocked_tasks from agent_tasks where status='blocked' and (title ilike '%smoke%' or description ilike '%smoke%');"

python3 -m py_compile \
  /root/.hermes/scripts/wolfy_usage_limit_watchdog.py \
  /root/.hermes/scripts/mike_safe_autorepair.py \
  /root/.hermes/scripts/wolfy_tiered_backfill_bounded.py \
  /root/.hermes/wolfy/visible_progress_ledger.py

WOLFY_CONTEXT_SMOKE=1 python3 /root/.hermes/scripts/wolfy_hourly_knowledge_context.py >/tmp/wolfy_hourly_smoke.out
python3 /root/.hermes/wolfy/visible_progress_ledger.py --format markdown --limit 3 >/tmp/ledger.md
python3 /root/.hermes/wolfy/visible_progress_ledger.py --format json --limit 3 >/tmp/ledger.json

hermes kanban --board wolfy list --assignee mike
```

## Interpretation

- If Python watchdog direct invocation and executable invocation both exit 0 and emit nothing, treat earlier shell-parse output from `bash /path/to/watchdog.py` as an invocation mistake, not a current watchdog break.
- If a no-agent job is just due while the current LLM Mike ops cron session is running, and `/root/.hermes/cron/.tick.lock` is fresh, do not report a stuck scheduler solely from the stale `Next run` timestamp. Cross-check logs and direct smokes; if they are clean, classify it as an active-tick artifact.
- Historical Jonah `tmp_*.py` scratch-query warnings are triage leads only. Do not add schema aliases or report user-facing breakage unless the exact durable probe still fails.
- If no code/config/schema was changed and all checks above pass, final response should be exactly `[SILENT]`.
