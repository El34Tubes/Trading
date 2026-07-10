# Wolfy multi-context budget wake-gate pattern — 2026-07-08

## Context
A Mike ops run found that budget protection had to cover all LLM-driven Wolfy cron context scripts, not just Jonah. The active `budget_gate.py` returned a hard block (`BUDGET=block token_cap_exceeded ...`), so visible/report LLM jobs needed to avoid waking the agent while script-only jobs kept running.

## Durable pattern
For LLM cron jobs with pre-run context scripts, place the budget check at the top of the live context implementation, before any task claim, `agent_runs` start, report row insert, or other mutation. On block, print a concise human-readable line if useful, then make the final non-empty stdout line JSON:

```json
{"wakeAgent": false, "reason": "budget"}
```

Cron parses the final JSON line as the wake gate; a plain `skipped: budget` line alone is not enough.

## Scripts covered in this run
The shared helper was `/root/.hermes/wolfy/budget_wake_gate.py`. The gate was wired into:

- `/root/.hermes/wolfy/alpha_search_context.py`
- `/root/.hermes/wolfy/wolfy_eod_screening_context.py`
- `/root/.hermes/wolfy/sentinel_review_context.py`
- `/root/.hermes/wolfy/yang_technical_context.py`
- `/root/.hermes/scripts/wolfy_eod_weekly_research_context.py`

The EOD screening wrapper was also synced across:

- `/root/.hermes/scripts/wolfy_eod_screening_context.py`
- `/root/.hermes/profiles/mike/scripts/wolfy_eod_screening_context.py`
- `/root/.hermes/profiles/clerky/scripts/wolfy_eod_screening_context.py`

## Verification recipe
Use real smokes and mutation guards before reporting success:

1. Compile every touched context and wrapper with `python3 -m py_compile`.
2. Force/observe a budget-block path and verify each context's last non-empty line is the JSON wake gate.
3. Record before/after counts for mutation-sensitive tables such as `agent_runs.status='started'`, `agent_tasks.status='in_progress'`, and context-specific report tables (for example `alpha_search_reports`) to prove skipped contexts did not claim work or create rows.
4. Smoke the pass path with `WOLFY_SKIP_BUDGET_GATE=1 WOLFY_CONTEXT_SMOKE=1` so normal context generation still works.
5. Run `mike_safe_autorepair.py` twice and verify the second run is silent, then confirm synced wrapper hashes where relevant.
6. Re-check Postgres guard, stale started runs, duplicate-claim noise, and embedding coverage.

## Reporting nuance
If the budget gate is actively blocking, report it as expected protective behavior, not a broken report pipeline. Script-only watchdogs/scanners/repair loops should continue. The next autonomous action is monitoring until the budget clears; the gated LLM context scripts should resume normal wake behavior automatically when `budget_gate.py` returns OK.
