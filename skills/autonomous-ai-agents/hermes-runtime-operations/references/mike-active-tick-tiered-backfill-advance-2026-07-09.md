# Mike active-tick tiered backfill advance — 2026-07-09

Context: Mike scheduled ops ran while the default-profile cron scheduler still showed `Wolfy bounded tiered EOD history backfill` as just due (`Next run` around 03:16) and `/root/.hermes/cron/.tick.lock` had just been touched by the active LLM ops cron session. Treat this shape as an active-tick artifact first, not immediate scheduler failure.

Safe response pattern:

1. Verify production/default cron, not only the active Mike profile:
   - `hermes --profile default cron list --all`
   - `hermes --profile default cron status`
   - inspect `/root/.hermes/cron/.tick.lock` age when status remains just-due.
2. If the due job is a bounded no-agent helper, run the exact wrapper directly as a smoke/advance step:
   - `python3 /root/.hermes/scripts/wolfy_tiered_backfill_bounded.py`
3. Capture real deltas from its JSONL output instead of just saying the smoke passed.
   - In this run it fetched 1002 bars for `ENS`/`ENSG` and 1002 bars for `ENTG`/`EQH`.
   - It created ingest/feature runs `1550–1553`.
   - Mid-cap ready coverage advanced from 104 to 108 tickers with >=495 bars; missing mid-cap fell from 256 to 252.
4. Verify persistence with direct Postgres counts:
   - per-ticker `count(*)` and `max(dt)` from `prices` for advanced symbols.
   - tier coverage using `universe` joined to `prices`, threshold `>=495` bars.
5. Re-check coordination health:
   - stale started runs = 0.
   - duplicate claim noise = 0.
   - synthetic smoke blockers = 0.
6. Compile the exact cron wrapper plus delegated implementation. Do not assume every cron wrapper also has a same-named Wolfy-local file.
   - Correct for this case: `/root/.hermes/scripts/wolfy_tiered_backfill_bounded.py` delegates to `/root/.hermes/wolfy/backfill_tiered_remaining.py`.

Reporting guidance:

- If this produces real data deltas, send a short report; do not return `[SILENT]`.
- Explain a still-stale `cron status` as unresolved/active-tick artifact only if direct smokes and DB persistence are healthy and the tick lock is fresh.
- Do not classify historical 429s or old scratch-query warnings as current blockers when usage watchdog/autorepair/coordination smokes are clean.
