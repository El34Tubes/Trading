# Wolfy visible ledger Python driver fallback — 2026-06-25

Session learning for the Wolfy/EOD visible-progress workflow.

## Context

Manual status work used `/root/.hermes/wolfy/visible_progress_ledger.py` to inspect Postgres facts before advising optimization priorities. The script initially produced `ModuleNotFoundError: No module named 'psycopg'` from system `python3`, even though cron/Hermes contexts may have psycopg3 available.

System Python on this host had `psycopg2` available but not `psycopg`. The durable fix was not to treat the ledger as broken or install packages mid-audit; it was to make the read-only helper tolerate both common Postgres drivers.

## Reusable pattern

For small read-only Wolfy status/context helpers that need to run from both manual shell checks and scheduled/Hermes contexts:

1. Prefer `psycopg`/psycopg3 when available, with `dict_row`.
2. Fall back to `psycopg2.connect(..., cursor_factory=psycopg2.extras.RealDictCursor)` when psycopg3 is missing.
3. Keep the helper read-only; do not approve strategies, create setups, mutate ledgers, or trade from a status script.
4. Verify with both compile and live smoke output:
   - `python3 -m py_compile /root/.hermes/wolfy/visible_progress_ledger.py`
   - `python3 /root/.hermes/wolfy/visible_progress_ledger.py --limit 5`
   - optionally `python3 /root/.hermes/wolfy/visible_progress_ledger.py --json --limit 2`

## Example connection shim

```python
def _connect(dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(dsn, row_factory=dict_row)
    except ModuleNotFoundError as exc:
        if exc.name != "psycopg":
            raise

    import psycopg2
    import psycopg2.extras
    return psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)
```

## Optimization audit lesson

Before recommending broader Wolfy optimizations, run the deterministic ledger or direct Postgres checks. In this session the useful facts were:

- Cron active/paused counts.
- Price/feature freshness and historical depth.
- Scanner freshness, especially stale `data_date` even when cron runs are current.
- Signals/setups/strategy-gate state.
- Candidate status versus approved status.
- Paper/accountability rows.
- Recent blockers such as LLM timeouts.

The priority conclusion was: do not increase report cadence until scanner freshness, strict candidate validation, and paper-ledger accountability are sound.