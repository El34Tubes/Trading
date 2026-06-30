# Wolfy tiered backfill runner + post-verification pattern (2026-06-27)

Context: after adding blue-chip / large-cap / mid-cap / small-cap / ETF core tier rules, the remaining Massive EOD historical pull was too large for one foreground command. Large one-shot batches risk timeout-before-commit and rate-limit churn.

Durable pattern:

1. Keep the selector separate from ingestion.
   - Tier selection lives in `wolfy_tiered_universe.py` and populates `universe_backfill_targets`.
   - Price/feature writes remain in `eod_price_features.py` / `massive_ingest()`.

2. Use a resumable runner for bulk tier backfills.
   - File created in-session: `/root/.hermes/wolfy/backfill_tiered_remaining.py`.
   - It queries active `universe_backfill_targets`, left-joins `prices`, and selects only symbols with fewer than 500 stored bars.
   - It runs `massive_ingest()` in commit-safe batches, default 10 symbols.
   - It logs JSONL progress events: `start`, `initial_counts`, `batch_start`, `batch_done`, `batch_error`, `tier_complete`, `deadline_reached`, `complete`.
   - It intentionally continues through limited failures and exits non-zero only after too many failures.

3. Run long backfills as background processes with a live log symlink.

Example:

```bash
LOG=/root/.hermes/wolfy/tiered_backfill_$(date -u +%Y%m%dT%H%M%SZ).log
ln -sfn "$LOG" /root/.hermes/wolfy/tiered_backfill_latest.log
uvx --with 'psycopg[binary]' python /root/.hermes/wolfy/backfill_tiered_remaining.py \
  --tiers large_cap mid_cap small_cap \
  --batch-size 10 \
  --days 730 \
  --pause-seconds 0.25 \
  --batch-sleep-seconds 1 \
  --max-failures 8 2>&1 | tee "$LOG"
```

4. Add a second background verifier that waits for the backfill PID instead of trusting completion by narrative.
   - File created in-session: `/root/.hermes/wolfy/post_tiered_backfill_verify.py`.
   - It waits for the backfill PID to exit.
   - It prints final tier counts.
   - It runs `eod_signals.py` across loaded target tickers using the common feature date.
   - It runs targeted regression tests: `test_wolfy_tiered_universe.py`, `test_eod_price_features.py`, `test_eod_signals.py`.

Example:

```bash
LOG=/root/.hermes/wolfy/tiered_backfill_post_verify_$(date -u +%Y%m%dT%H%M%SZ).log
ln -sfn "$LOG" /root/.hermes/wolfy/tiered_backfill_post_verify_latest.log
uvx --with 'psycopg[binary]' python /root/.hermes/wolfy/post_tiered_backfill_verify.py \
  --wait-pid <BACKFILL_PID> \
  --poll-seconds 60 2>&1 | tee "$LOG"
```

5. Report in-progress truthfully.
   - Do not say the full universe is loaded until DB counts show it.
   - Give the user the process/session id, PID, log paths, and current tier counts.
   - Say explicitly when the job will take hours due to provider rate limits.

Useful progress query:

```sql
select t.tier,
       count(*) as targets,
       count(*) filter (where coalesce(p.bars,0)>=500) as loaded_500,
       count(*) filter (where coalesce(p.bars,0)>0 and coalesce(p.bars,0)<500) as partial,
       count(*) filter (where coalesce(p.bars,0)=0) as missing
from universe_backfill_targets t
left join (select ticker, count(*) bars from prices group by ticker) p
  on p.ticker=t.symbol
where t.active
group by t.tier
order by min(t.priority), t.tier;
```

Operational notes:

- Use `uvx --with 'psycopg[binary]' python ...` for manual Postgres helpers when system Python lacks psycopg.
- Skip expensive validation during bulk historical backfill (`validate=False` / `--no-validate`) and verify quality/signals after batches land.
- A partially loaded blue-chip tier can occur when a symbol has fewer than 500 bars; distinguish `loaded_500`, `partial`, and `missing` rather than a simple loaded/missing boolean.
