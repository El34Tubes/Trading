# Mike active-tick mid-cap backfill advance (2026-07-10)

## Context
A Mike autonomous environment triage cron run found default-profile no-agent jobs whose `Next run` timestamps were just due/stale while the current Mike LLM ops run was active and `/root/.hermes/cron/.tick.lock` had just been touched. Gateway logs showed only housekeeping, and no stale started coordination rows existed.

## Durable workflow
1. Treat just-due no-agent jobs during an active Mike LLM tick as active-tick context first, not an immediate scheduler incident.
2. Verify safe script-only helpers directly instead of waiting: usage watchdog twice, stale coordination cleanup, usage snapshot, embedding sync, safe autorepair twice, config guardian, and budget-gated context smokes.
3. For bounded tiered backfill, it is safe to manually run the exact no-agent wrapper once as an advance/smoke step while the active LLM tick is running:
   ```bash
   python3 /root/.hermes/scripts/wolfy_tiered_backfill_bounded.py
   ```
4. Capture real before/after progress with `prices` coverage and the wrapper JSON output. In this run the wrapper advanced mid-cap tickers `NVST`, `NVT`, `NWE`, and `NXST`, adding 2,004 `prices` rows; each ended with 501 bars from `2024-07-10` to `2026-07-09`.
5. Do not query `universe_backfill_targets.latest_dt`; that alias may not exist. Derive coverage from `prices`:
   ```sql
   select ticker, count(*) bars, min(dt) first_dt, max(dt) last_dt
   from prices
   where ticker in ('NVST','NVT','NWE','NXST')
   group by ticker
   order by ticker;
   ```
6. If the active ops run itself is the only `agent_runs.status='started'` row and is only a few minutes old, do not close it as stale.

## Reporting rule
If the manual bounded backfill produced real ticker/bar deltas, report those concrete deltas. If all direct smokes are silent and no state changed, return exactly `[SILENT]` for scheduled Mike ops delivery.
