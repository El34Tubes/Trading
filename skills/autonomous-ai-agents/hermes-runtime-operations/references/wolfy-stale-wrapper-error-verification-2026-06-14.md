# Wolfy stale wrapper error verification (2026-06-14)

## Context
A Mike autonomous environment triage run received a pre-run `recent errors tail` containing an older failure:

- `missing: /root/.hermes/wolfy/wolfy_sentinel_review_context.py`
- `/root/.hermes/wolfy/wolfy_yang_technical_context.py`

By the time the triage ran, the files had already been restored/synced by prior repair work. Treating the log tail as current truth would have caused duplicate/no-op edits or a false user-facing repair claim.

## Safe verification pattern
Before editing, verify current state directly across the invocation layers that cron/profile diagnostics may use:

```bash
# Discover current wrappers/implementations
python3 -m py_compile \
  /root/.hermes/wolfy/wolfy_sentinel_review_context.py \
  /root/.hermes/wolfy/sentinel_review_context.py \
  /root/.hermes/wolfy/wolfy_yang_technical_context.py \
  /root/.hermes/wolfy/yang_technical_context.py \
  /root/.hermes/scripts/wolfy_sentinel_review_context.py \
  /root/.hermes/scripts/wolfy_yang_technical_context.py \
  /root/.hermes/profiles/mike/scripts/wolfy_sentinel_review_context.py \
  /root/.hermes/profiles/yang/scripts/wolfy_yang_technical_context.py

# Smoke without opening durable agent_runs rows
cd /root/.hermes/wolfy
WOLFY_CONTEXT_SMOKE=1 python3 wolfy_sentinel_review_context.py >/tmp/sentinel_smoke.out
WOLFY_CONTEXT_SMOKE=1 python3 wolfy_yang_technical_context.py >/tmp/yang_smoke.out

# Autorepair must be idempotent/silent
python3 /root/.hermes/scripts/mike_safe_autorepair.py >/tmp/autorepair1.out
python3 /root/.hermes/scripts/mike_safe_autorepair.py >/tmp/autorepair2.out
wc -c /tmp/autorepair1.out /tmp/autorepair2.out
```

Then run the normal read-only operations checks:

```bash
/root/.hermes/wolfy/check_postgres_requirements.py
psql -d wolfy -X -v ON_ERROR_STOP=1 -c "select count(*) filter (where status='started' and started_at < now() - interval '2 hours') as stale_started_runs, count(*) filter (where status='blocked' and error_message='duplicate-or-already-claimed' and started_at > now() - interval '3 hours') as recent_duplicate_claim_noise from agent_runs;"
python3 /root/.hermes/scripts/wolfy_cleanup_stale_agent_coordination.py >/tmp/cleanup.out
python3 /root/.hermes/scripts/wolfy_embed_knowledge_chunks.py >/tmp/embed.out
python3 /root/.hermes/scripts/wolfy_capture_usage_snapshot.py >/tmp/usage.out
```

## Reporting rule
If the direct checks pass and no files needed edits, say no repair was needed and list the verification. Do not claim the old log-tail error is still active, and do not say you fixed it in this run unless you actually changed files/DB state.
