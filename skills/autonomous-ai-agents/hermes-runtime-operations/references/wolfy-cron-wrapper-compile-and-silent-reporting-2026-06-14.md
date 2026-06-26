# Wolfy cron wrapper compile checks and silent reporting (2026-06-14)

Lesson from a Mike autonomous environment triage run.

## Context

The injected triage context showed all default-profile Wolfy cron jobs healthy, Postgres guard OK, no stale coordination rows, embedding coverage complete, and no output from script-only smokes. A quick manual compile check initially failed because it tried to compile nonexistent live paths such as:

- `/root/.hermes/wolfy/wolfy_sentinel_review_context.py`
- `/root/.hermes/wolfy/wolfy_yang_technical_context.py`

Those were not real failures. The cron-facing wrappers live under `/root/.hermes/scripts/` with legacy/prefixed names, and delegate to unprefixed live implementations:

- `/root/.hermes/scripts/wolfy_sentinel_review_context.py` -> `/root/.hermes/wolfy/sentinel_review_context.py`
- `/root/.hermes/scripts/wolfy_yang_technical_context.py` -> `/root/.hermes/wolfy/yang_technical_context.py`

## Safe verification pattern

When checking cron scripts, verify the exact layer cron invokes plus the delegated implementation:

```bash
python3 -m py_compile \
  /root/.hermes/wolfy/sentinel_review_context.py \
  /root/.hermes/wolfy/yang_technical_context.py \
  /root/.hermes/scripts/wolfy_sentinel_review_context.py \
  /root/.hermes/scripts/wolfy_yang_technical_context.py
```

For Jonah hourly knowledge context, cron invokes `/root/.hermes/scripts/wolfy_hourly_knowledge_context.py`, which delegates to `/root/.hermes/wolfy/hourly_knowledge_context.py`; do not require a live file named `/root/.hermes/wolfy/wolfy_hourly_knowledge_context.py` unless a real consumer calls it.

## Reporting rule

For scheduled Mike ops runs with explicit silent delivery semantics, if diagnostics and safe smokes show no current actionable issue and no fix was made, final output should be exactly:

```text
[SILENT]
```

Do not send a status report just to confirm everything is healthy; the cron delivery layer suppresses `[SILENT]`.