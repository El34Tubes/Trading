# Mike active-tick + bounded tiered backfill advance (2026-07-08)

When the Mike LLM ops cron session is running, `hermes --profile default cron status` and `cron list` can temporarily keep showing just-due no-agent jobs at their old `Next run` timestamp because the active LLM run is holding the scheduler tick. Do not immediately classify this as a stuck scheduler.

## Safe triage pattern

1. Confirm gateway is running and identify the active Mike ops session / fresh tick lock.
2. Treat direct script smokes as the source of truth for no-agent jobs while the active LLM run is open.
3. For safe bounded jobs, manually run the exact script once as a smoke/advance step instead of waiting:
   - `/root/.hermes/scripts/wolfy_tiered_backfill_bounded.py`
   - `/root/.hermes/scripts/mike_safe_autorepair.py`
   - `/root/.hermes/scripts/wolfy_cleanup_stale_agent_coordination.py`
   - `/root/.hermes/scripts/wolfy_embed_knowledge_chunks.py`
   - `/root/.hermes/scripts/wolfy_usage_limit_watchdog.py`
4. Report real state deltas, not just that the smoke passed. For tiered backfill, capture before/after counts by tier and the specific tickers advanced.

## Concrete observed output

Bounded tiered backfill safely advanced mid-cap history during an active Mike tick:

- Initial mid-cap readiness: `44 loaded_500`, `316 missing`, `360 targets`.
- Ran two batches for `BSY`, `BURL`, `BWA`, `BWXT`.
- Each batch fetched `1002` bars and produced ingest/feature run IDs.
- Final mid-cap readiness: `48 loaded_500`, `312 missing`, `360 targets`.

## Reporting rule

If the only `agent_runs.status='started'` row is the current Mike ops cron session (`cron_job_id=fdfd5b53b5d5`, fresh age), explain it as expected and do not treat it as stale ledger noise. If the manual no-agent smokes are silent/OK and the bounded backfill advanced real rows, report those deltas concisely; otherwise return `[SILENT]` only when there was genuinely no state change or actionable warning.