# Wolfy visible progress ledger CLI compatibility (2026-06-20)

## Trigger

A Mike/Wolfy operations run found that `/root/.hermes/wolfy/visible_progress_ledger.py` was fundamentally healthy, but manual/cron smoke probes used tolerant convenience arguments that the helper did not yet accept:

```bash
python3 /root/.hermes/wolfy/visible_progress_ledger.py --format markdown --limit 5
```

The helper originally only accepted `--json` and `--dsn`, so the probe failed with `error: unrecognized arguments: --format markdown --limit 5`. A previous run had also hit `Permission denied` when invoking the helper directly, so executable bit preservation mattered too.

## Durable fix pattern

For deterministic, read-only Wolfy status helpers that may be called by several ops/planner scripts, prefer tolerant CLI compatibility over forcing every caller to know the narrowest argument set.

1. Keep the helper read-only: no DB writes, no strategy approval, no setup creation.
2. Preserve legacy flags such as `--json`.
3. Add explicit compatibility aliases when ops probes naturally use them:
   - `--format markdown|json`
   - `--limit N` for compact Markdown blocker rows
4. Restore executable mode if the helper may be called directly:
   ```bash
   chmod 755 /root/.hermes/wolfy/visible_progress_ledger.py
   ```
5. Verify both forms:
   ```bash
   python3 -m py_compile /root/.hermes/wolfy/visible_progress_ledger.py
   python3 /root/.hermes/wolfy/visible_progress_ledger.py --format markdown --limit 2 > /tmp/wolfy_visible_progress_ledger.md
   python3 /root/.hermes/wolfy/visible_progress_ledger.py --format json > /tmp/wolfy_visible_progress_ledger.json
   python3 -m json.tool /tmp/wolfy_visible_progress_ledger.json >/dev/null
   python3 /root/.hermes/scripts/mike_safe_autorepair.py
   python3 /root/.hermes/scripts/mike_safe_autorepair.py
   ```
6. Record the compatibility follow-up in `/root/.hermes/wolfy/optimization_todo.md` so future optimization runs know the helper was intentionally broadened.

## Scheduler interpretation pitfall

If a Mike LLM-driven cron job is active while just-due script-only jobs show stale `Next run` timestamps, do not immediately classify the scheduler as stuck. Cross-check logs/processes and wait for the active LLM cron run to exit; only report scheduler trouble if timestamps remain stale afterward.

## What not to persist

Do not encode a negative rule like “visible_progress_ledger is broken” or “cron is stuck.” The durable learning is the compatibility pattern and verification sequence, not the transient failure.