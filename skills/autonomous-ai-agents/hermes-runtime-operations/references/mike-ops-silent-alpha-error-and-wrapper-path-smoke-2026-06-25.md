# Mike ops: stale Alpha Search last_error + exact wrapper-path smoke (2026-06-25)

## Context
A scheduled Mike environment triage run saw the default-profile cron entry for `Wolfy separate Alpha Search Report` still showing `last_status=error` with a timeout message mentioning `gpt-5.5`. The raw cron config for the same job already had `model: "gpt-5.4"`, and a direct one-shot smoke with that exact profile/model succeeded:

```bash
hermes --profile default chat -Q -m gpt-5.4 -q 'Runtime smoke: reply with exactly OK.'
# -> OK
```

Postgres coordination and script-only smokes were healthy, so the stale `last_error` was not treated as a new incident.

## Durable workflow
1. Inspect the raw cron config or `hermes --profile default cron list --all` before acting on old `last_error` text.
2. If the saved job already has a fallback model, run a direct smoke with that exact profile/model before changing the job.
3. Check ledger hygiene before reporting: `stale_started_runs=0`, duplicate-claim noise is zero, embedding/cleanup/usage smokes are silent.
4. Re-run `mike_safe_autorepair.py` twice; the second run should be silent.
5. Compile exact wrapper paths, not guessed local filenames. In this run, `wolfy_eod_screening_context.py` existed as `/root/.hermes/scripts/wolfy_eod_screening_context.py`, while `visible_progress_ledger.py` was under `/root/.hermes/wolfy/`.
6. Verify visible ledger Markdown and JSON modes directly.
7. If everything is healthy and the only remaining item is the old cron `last_error` waiting for the next scheduled retry, respond exactly `[SILENT]` for silent Mike ops delivery.

## Commands used

```bash
/root/.hermes/wolfy/check_postgres_requirements.py
hermes --profile default cron list --all
hermes --profile default chat -Q -m gpt-5.4 -q 'Runtime smoke: reply with exactly OK.'

python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py

python3 -m py_compile \
  /root/.hermes/scripts/wolfy_eod_screening_context.py \
  /root/.hermes/wolfy/visible_progress_ledger.py \
  /root/.hermes/wolfy/wolfy_alpha_search_context.py \
  /root/.hermes/wolfy/wolfy_hourly_knowledge_context.py \
  /root/.hermes/wolfy/wolfy_sentinel_review_context.py \
  /root/.hermes/wolfy/wolfy_yang_technical_context.py

python3 /root/.hermes/wolfy/visible_progress_ledger.py --format markdown --limit 5
python3 /root/.hermes/wolfy/visible_progress_ledger.py --format json --limit 5

python3 /root/.hermes/scripts/wolfy_usage_limit_watchdog.py
python3 /root/.hermes/scripts/wolfy_cleanup_stale_agent_coordination.py
python3 /root/.hermes/scripts/wolfy_embed_knowledge_chunks.py
python3 /root/.hermes/scripts/wolfy_capture_usage_snapshot.py
```

## Pitfall
Avoid compiling or probing assumed relative filenames just because the cron job lists a script name. Resolve the actual invocation layer first: global `/root/.hermes/scripts/`, Wolfy-local `/root/.hermes/wolfy/`, and any profile wrapper paths.