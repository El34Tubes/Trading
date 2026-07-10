# Mike weekly EOD wrapper sync + budget gate smoke (2026-07-08)

## Trigger
Mike ops pre-run showed a recent `read_file` warning for `/root/.hermes/wolfy/wolfy_eod_weekly_research_context.py` while the only existing weekly context script was global-only at `/root/.hermes/scripts/wolfy_eod_weekly_research_context.py`.

## Durable fix pattern
1. Treat global-only cron context scripts as wrapper-sync drift when diagnostics or profile-scoped jobs may probe Wolfy-local/profile paths.
2. Patch canonical `/root/.hermes/scripts/mike_safe_autorepair.py` first, not a copied profile/Wolfy copy.
3. Add the script name to:
   - `MIKE_SCRIPTS`
   - `CLERKY_SCRIPTS`
   - `WOLFY_SCRIPTS_FROM_GLOBAL`
4. Run autorepair twice:
   - first run should report copied/synced files
   - second run should be silent
5. Compile every invocation layer:
   - `/root/.hermes/scripts/mike_safe_autorepair.py`
   - `/root/.hermes/wolfy/mike_safe_autorepair.py`
   - profile copies under Mike/Clerky
   - global/Wolfy/profile copies of the repaired context wrapper
6. Smoke the repaired context wrapper with the same interpreter cron uses. If Wolfy budget gate is active, a healthy smoke is:
   - human line like `skipped: budget ...`
   - final non-empty JSON line `{"wakeAgent": false, "reason": "budget"}`

## Verification commands used
```bash
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 -m py_compile \
  /root/.hermes/scripts/mike_safe_autorepair.py \
  /root/.hermes/wolfy/mike_safe_autorepair.py \
  /root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py \
  /root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py \
  /root/.hermes/scripts/wolfy_eod_weekly_research_context.py \
  /root/.hermes/wolfy/wolfy_eod_weekly_research_context.py \
  /root/.hermes/profiles/mike/scripts/wolfy_eod_weekly_research_context.py \
  /root/.hermes/profiles/clerky/scripts/wolfy_eod_weekly_research_context.py
python3 /root/.hermes/scripts/wolfy_eod_weekly_research_context.py
```

## Reporting nuance
If no-agent cron jobs still show just-due `Next run` timestamps while the current Mike LLM cron session is active and direct no-agent smokes are clean, classify that as an active-tick artifact and poll after the active run exits rather than reporting a stuck scheduler.
