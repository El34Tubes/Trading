# Wolfy tiered backfill: avoid duplicate tickers inside one bounded run (2026-07-23)

## Trigger

Mike ops found a due `Wolfy bounded tiered EOD history backfill` while an active cron tick was in progress. Manual bounded smoke advanced small-cap coverage, but the two-batch wrapper selected `FDP` in both batches because the ticker remained below the readiness threshold after the first fetch.

## Durable lesson

For bounded tiered Massive/EOD backfill runners, do not only filter on persisted coverage between batches. Maintain an in-run `attempted_this_run` exclusion set and pass it to target selection. This lets a naturally short or still-missing ticker retry on the next cron tick, but prevents it from consuming multiple scarce batches in the same cron run.

## Safe implementation shape

- Keep existing readiness logic:
  - no-price tickers are eligible immediately;
  - partial-history tickers are eligible only when stale, e.g. `latest_dt < current_date - interval '5 days'`.
- Add an optional `exclude` parameter to `remaining_tickers(...)`.
- In `run(...)`, initialize `attempted_this_run: set[str] = set()`.
- Pass `exclude=sorted(attempted_this_run)` into each target-selection call.
- After selecting a batch and before ingesting, call `attempted_this_run.update(tickers)`.

## Verification pattern

1. Compile the delegated implementation and cron wrappers:
   ```bash
   python3 -m py_compile /root/.hermes/wolfy/backfill_tiered_remaining.py \
     /root/.hermes/scripts/wolfy_tiered_backfill_bounded.py \
     /root/.hermes/wolfy/wolfy_tiered_backfill_bounded.py
   ```
2. Run a read-only selection smoke that calls `remaining_tickers(..., exclude=first_batch)` and assert overlap is empty.
3. Run the bounded wrapper once only when it is due/safe; report real tier count deltas from `prices` coverage joined to `universe_backfill_targets`.
4. Re-check cron list: a just-due `Next run` should advance after the active tick; do not call scheduler stuck solely from a stale timestamp during the current Mike LLM run.

## Reporting nuance

If the manual smoke advances coverage, report the exact before/after counts, run IDs, and tickers advanced. If all other smokes are clean and only a due timestamp is stale during an active tick, treat it as active-tick context rather than a scheduler incident.