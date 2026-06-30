# Wolfy EOD context: filter synthetic test run rows (2026-06-26)

## Trigger
Mike ops found `wolfy_eod_screening_context.py` was showing synthetic unit-test rows from the shared Postgres `runs` table in the user-facing EOD screening context. The live EOD jobs were healthy, but local tests had inserted rows with sources such as `unit-backtest` and synthetic tickers like `ZZBT`, which made the EOD report context look like it was driven by test fixtures.

## Safe fix pattern
Patch the user-facing context query, not the historical `runs` data:

```sql
SELECT job, started, finished, status, detail
FROM runs
WHERE job IN ('eod_price_ingest','eod_feature_compute')
  AND NOT (
      coalesce(detail->>'source', '') LIKE 'unit-%'
      OR EXISTS (
          SELECT 1
          FROM jsonb_array_elements_text(coalesce(detail->'tickers', '[]'::jsonb)) AS ticker(value)
          WHERE ticker.value LIKE 'ZZ%'
      )
  )
ORDER BY started DESC
LIMIT 6;
```

This preserves the test rows for debugging/accountability while preventing them from polluting user-visible EOD context.

## Preservation layers
After patching the canonical/global wrapper, run `mike_safe_autorepair.py` so the change syncs to all expected invocation layers:

- `/root/.hermes/scripts/wolfy_eod_screening_context.py`
- `/root/.hermes/wolfy/wolfy_eod_screening_context.py`
- `/root/.hermes/profiles/mike/scripts/wolfy_eod_screening_context.py`
- `/root/.hermes/profiles/clerky/scripts/wolfy_eod_screening_context.py`

Add a regression test that asserts the script contains the synthetic-row guards (`unit-%`, `jsonb_array_elements_text`, and `ZZ%`) so future refactors do not reintroduce the user-facing fixture leak.

## Verification recipe

```bash
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 -m py_compile \
  /root/.hermes/scripts/wolfy_eod_screening_context.py \
  /root/.hermes/wolfy/wolfy_eod_screening_context.py \
  /root/.hermes/profiles/mike/scripts/wolfy_eod_screening_context.py \
  /root/.hermes/profiles/clerky/scripts/wolfy_eod_screening_context.py
cd /root/.hermes/wolfy && /usr/local/lib/hermes-agent/venv/bin/python -m pytest test_eod_governance.py -q -o 'addopts='
WOLFY_CONTEXT_SMOKE=1 python3 /root/.hermes/scripts/wolfy_eod_screening_context.py >/tmp/wolfy_eod_context_smoke.out
if grep -q 'unit-' /tmp/wolfy_eod_context_smoke.out; then
  echo 'FOUND_UNIT_ROWS'
  exit 1
fi
```

Expected: autorepair second run is silent, compile passes, regression passes, and the context smoke shows live `yahoo-chart-delayed`/real ticker runs rather than `unit-*` rows.