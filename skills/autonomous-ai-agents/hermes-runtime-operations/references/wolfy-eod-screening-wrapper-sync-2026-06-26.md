# Wolfy EOD screening wrapper sync (2026-06-26)

## Trigger

Mike ops pre-run/cron logs showed a stale path error for `wolfy_eod_screening_context.py` and a direct compile check against `/root/.hermes/wolfy/wolfy_eod_screening_context.py` failed because the live cron-owned implementation only existed under `/root/.hermes/scripts/`.

## Durable fix pattern

For profile/cron-facing context helpers, verify every layer that may be invoked:

- Live/global cron implementation: `/root/.hermes/scripts/wolfy_eod_screening_context.py`
- Wolfy-local compatibility path: `/root/.hermes/wolfy/wolfy_eod_screening_context.py`
- Mike profile wrapper: `/root/.hermes/profiles/mike/scripts/wolfy_eod_screening_context.py`
- Clerky profile wrapper: `/root/.hermes/profiles/clerky/scripts/wolfy_eod_screening_context.py`

Patch canonical `/root/.hermes/scripts/mike_safe_autorepair.py` first so the fix survives future runs:

1. Add `wolfy_eod_screening_context.py` to `MIKE_SCRIPTS`.
2. Add it to `CLERKY_SCRIPTS` if profile-scoped diagnostics may probe it.
3. Add it to `WOLFY_SCRIPTS_FROM_GLOBAL` when the source of truth is the global cron script and the Wolfy-local path should be an exact synced copy.
4. Run global autorepair twice:
   ```bash
   python3 /root/.hermes/scripts/mike_safe_autorepair.py
   python3 /root/.hermes/scripts/mike_safe_autorepair.py
   ```
   The first run may report synced files; the second run should be silent.

## Verification commands used

```bash
python3 -m py_compile \
  /root/.hermes/scripts/wolfy_eod_screening_context.py \
  /root/.hermes/wolfy/wolfy_eod_screening_context.py \
  /root/.hermes/profiles/mike/scripts/wolfy_eod_screening_context.py \
  /root/.hermes/profiles/clerky/scripts/wolfy_eod_screening_context.py \
  /root/.hermes/scripts/mike_safe_autorepair.py \
  /root/.hermes/wolfy/mike_safe_autorepair.py \
  /root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py \
  /root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py

WOLFY_CONTEXT_SMOKE=1 python3 /root/.hermes/scripts/wolfy_eod_screening_context.py >/tmp/eod_context.out
python3 /root/.hermes/wolfy/wolfy_eod_screening_context.py >/tmp/eod_context_wolfy.out
wc -l /tmp/eod_context.out /tmp/eod_context_wolfy.out
```

Expected result: compile passes; both global and Wolfy-local context scripts produce comparable non-empty context output.

## Reporting nuance

Do not claim the EOD screening cron is broken if the live cron script path is healthy and the only failure was an older diagnostic probing a missing compatibility path. Report the wrapper sync repair and the successful smoke outputs.