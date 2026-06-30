# Wolfy orchestration refactor audit — 2026-06-29

## Context

The user asked whether the Wolfy orchestration layer had refactoring opportunities. A read-only audit checked default-profile cron state, wrapper inventory, duplicated constants, and git status.

## Findings

- Script-only backend loops were active while several LLM/report jobs were paused by provider usage limits.
- Cron jobs call exact script filenames, so wrapper filenames are operational interfaces and should not be renamed casually.
- Core EOD ticker universe was duplicated in:
  - `/root/.hermes/scripts/wolfy_eod_after_close_ingest.py`
  - `/root/.hermes/scripts/wolfy_eod_features_signals.py`
- EOD shard ticker groups were hard-coded across five wrappers:
  - `/root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_1.py`
  - ... `_5.py`
- Wrapper/profile sync remains a maintenance burden because some scripts are mirrored across global/default and profile paths.
- `mike_safe_autorepair.py` was over 1,100 lines and copied across locations, but it is a live guardrail and should not be the first broad refactor target.
- Working tree already contained many modified/untracked operational files, so broad refactors should be staged in narrow verified slices.

## Recommended refactor order

1. **Centralize orchestration config** in a small shared module such as `/root/.hermes/wolfy/orchestration_config.py`:
   - `CORE_EOD_UNIVERSE`
   - `EOD_INGEST_SHARDS`
   - `DEFAULT_EOD_LOOKBACK_DAYS = 730`
   - `DEFAULT_EOD_SOURCE = "massive"`
   - `DEPTH_READY_BARS = 495`
   - common Wolfy script paths / DSN constants if needed

2. **Preserve cron-facing script names as thin shims**:
   - Keep existing scripts under `/root/.hermes/scripts/` so cron metadata does not need a risky rewrite.
   - Move shared constants and runner behavior behind those wrappers.
   - Do not rename/delete wrapper scripts in the same slice.

3. **Add a shared orchestration runner** such as `/root/.hermes/wolfy/orchestration_runner.py` for:
   - subprocess invocation
   - compact JSON logging
   - consistent exit-code conventions
   - dry-run handling
   - environment/path setup
   - ticker-list validation

4. **Add read-only cron/job registry visibility** after wrapper consolidation:
   - Classify jobs by lane: `data`, `signals`, `LLM-report`, `review`, `ops-watchdog`, `backfill`.
   - Classify mode: `no-agent` vs LLM.
   - Surface pause reason where known, especially provider usage-limit pauses.
   - Use this to answer “are we looping?” without manually parsing raw cron text each time.

5. **Defer autorepair decomposition** until focused tests exist:
   - Split checks from repairs.
   - Separate wrapper-sync checks from DB/cron health checks.
   - Keep operations idempotent/read-only unless explicitly repairing.

## Verification pattern

For any orchestration refactor slice:

```bash
python3 -m py_compile /root/.hermes/wolfy/orchestration_config.py /root/.hermes/wolfy/orchestration_runner.py
python3 -m py_compile /root/.hermes/scripts/wolfy_eod_after_close_ingest.py /root/.hermes/scripts/wolfy_eod_features_signals.py
python3 /root/.hermes/scripts/wolfy_eod_after_close_ingest.py --dry-run
python3 /root/.hermes/scripts/wolfy_eod_features_signals.py --dry-run
python3 /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_1.py  # only if safe for current rate/window, otherwise add a dry-run mode first
hermes --profile default cron list --all
```

## Pitfalls

- Do not rewrite `cron/jobs.json` as part of the first refactor; operational JSON churn hides real changes.
- Do not break exact script filenames cron uses.
- Do not refactor `mike_safe_autorepair.py` first; it is a live guardrail with a higher blast radius.
- Do not combine wrapper consolidation, profile sync, cron metadata edits, and autorepair decomposition in one slice.
- Keep the EOD/no-auto-execution/human-approval constitution unchanged; orchestration refactors must not approve strategies, create setups, or imply trading authority.
