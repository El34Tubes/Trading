# Wolfy SQLite retirement / Postgres-only cutover — 2026-06-07

## Trigger

The user wanted to cut token-heavy reporting because of rate limits, keep autonomous work moving, and finish retiring SQLite in favor of Postgres.

## Durable lessons

- This is a class of **operational migration + cadence tuning**, not a narrative market-report task.
- Prefer script/data/cache verification first; use the LLM only for concise synthesis, ranking, exceptions, and user-facing decisions.
- For Wolfy, live operational writes/reads should use Postgres. SQLite may remain only as a legacy/archive/test artifact until explicitly deleted.
- Do not delete a legacy DB immediately after migration. Recommend a short observation window with clean cron cycles, then archive/delete with backup.
- When provider usage limits are active, do not force LLM cron jobs into repeated 429 failures. Keep script-only jobs running and resume LLM jobs after watchdog/credential checks clear.

## Migration checklist

1. Inventory live SQLite consumers:
   - `/root/.hermes/wolfy/*.py`
   - `/root/.hermes/scripts/*wolfy*`, profile wrappers, and any legacy wrapper paths
   - Hermes cron prompts/jobs for Wolfy, Jonah, Sentinel, Yang, Clerky, Mike
   - context generators and Alpha Search persistence/report scripts
2. Classify each SQLite reference:
   - live path to migrate/block
   - legacy inspection/archive path
   - compatibility wrapper/comment/doc reference
3. Patch live components to Postgres:
   - scanner/report context
   - Jonah knowledge context
   - Alpha Search context/persistence
   - storage/status metrics
   - cron prompts that still instruct SQLite writes
4. Keep outputs concise:
   - tables/bullets only
   - no filler sentences
   - explicitly challenge unsafe/low-value requests
   - recommend the best next move, not a neutral list
5. Verify before reporting done:
   - Python compile checks for touched scripts
   - representative context script execution
   - Postgres row counts for core tables such as `scanner_runs`, `scanner_results`, `alpha_leads`, `universe_symbols`, `system_metrics`
   - cron prompt/job JSON validity if edited
   - usage-limit status before resuming LLM-driven jobs

## User-facing wording pattern

Use a compact result table:

| Area | Result |
|---|---|
| Reporting style | Brief/no filler/challenger mode updated. |
| SQLite retirement | Live paths migrated to Postgres-only; SQLite remains legacy archive. |
| Verification | Include exact smoke-test outputs/counts. |
| Rate limits | Say whether LLM jobs are paused/blocked and whether script-only jobs continue. |

Then add one direct recommendation, e.g.:

> Do not delete `wolfy.db` today. It is no longer the live write path; archive/delete it only after a few clean Postgres-only cron cycles.

## Anti-patterns

- Claiming migration is complete without running real compile/smoke checks.
- Repeating long reports during a rate-limit reduction request.
- Treating any SQLite fallback in a live path as acceptable after the user asked for Postgres-only.
- Deleting the old SQLite DB for symbolic cleanliness before backup/observation.
