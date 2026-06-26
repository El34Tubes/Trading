# Wolfy Sentinel/Yang context wrapper sync (2026-06-14)

## Trigger

A Mike autonomous environment triage run reported missing live legacy-prefixed context wrappers even though the unprefixed live implementations and global wrappers existed:

- `/root/.hermes/wolfy/wolfy_sentinel_review_context.py` missing while `/root/.hermes/wolfy/sentinel_review_context.py` existed
- `/root/.hermes/wolfy/wolfy_yang_technical_context.py` missing while `/root/.hermes/wolfy/yang_technical_context.py` existed
- global wrappers under `/root/.hermes/scripts/` existed and cron jobs were still `ok`

This is a compatibility-wrapper preservation issue, not a market-analysis issue.

## Safe repair pattern

Patch `/root/.hermes/scripts/mike_safe_autorepair.py` so the wrapper sync survives future runs:

1. Add `wolfy_sentinel_review_context.py` and `wolfy_yang_technical_context.py` to `MIKE_SCRIPTS` when Mike/profile diagnostics need to compile or smoke the exact cron wrapper paths.
2. Add global `LEGACY_WRAPPERS` entries that delegate to:
   - `/root/.hermes/wolfy/sentinel_review_context.py`
   - `/root/.hermes/wolfy/yang_technical_context.py`
3. Add Wolfy-local `LEGACY_WOLFY_WRAPPERS` entries that delegate from:
   - `/root/.hermes/wolfy/wolfy_sentinel_review_context.py` -> `sentinel_review_context.py`
   - `/root/.hermes/wolfy/wolfy_yang_technical_context.py` -> `yang_technical_context.py`
4. Run the autorepair script once to materialize/sync wrappers.
5. Re-run it; the second run should be silent.

## Verification commands

Use smoke mode so verification does not claim work or leave `agent_runs.status='started'` rows:

```bash
python3 -m py_compile \
  /root/.hermes/scripts/mike_safe_autorepair.py \
  /root/.hermes/wolfy/mike_safe_autorepair.py \
  /root/.hermes/wolfy/wolfy_sentinel_review_context.py \
  /root/.hermes/wolfy/sentinel_review_context.py \
  /root/.hermes/scripts/wolfy_sentinel_review_context.py \
  /root/.hermes/profiles/mike/scripts/wolfy_sentinel_review_context.py \
  /root/.hermes/wolfy/wolfy_yang_technical_context.py \
  /root/.hermes/wolfy/yang_technical_context.py \
  /root/.hermes/scripts/wolfy_yang_technical_context.py \
  /root/.hermes/profiles/mike/scripts/wolfy_yang_technical_context.py \
  /root/.hermes/profiles/yang/scripts/wolfy_yang_technical_context.py

python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py  # should be silent

WOLFY_CONTEXT_SMOKE=1 python3 /root/.hermes/wolfy/wolfy_sentinel_review_context.py | grep 'SMOKE_MODE=true'
WOLFY_CONTEXT_SMOKE=1 python3 /root/.hermes/wolfy/wolfy_yang_technical_context.py | grep 'SMOKE_MODE=true'
WOLFY_CONTEXT_SMOKE=1 python3 /root/.hermes/profiles/yang/scripts/wolfy_yang_technical_context.py | grep 'SMOKE_MODE=true'

/root/.hermes/wolfy/check_postgres_requirements.py
psql -d wolfy -X -c "select count(*) filter (where status='started' and started_at < now() - interval '2 hours') as stale_started_runs from agent_runs;"
```

If the Yang profile wrapper exists but is not executable, `chmod 755 /root/.hermes/profiles/yang/scripts/wolfy_yang_technical_context.py` is safe and reversible.

## Reporting

Report this as fixed wrapper/autorepair preservation. Do not claim Sentinel/Yang market logic changed; the repair only preserves invocation paths and smoke-testability.