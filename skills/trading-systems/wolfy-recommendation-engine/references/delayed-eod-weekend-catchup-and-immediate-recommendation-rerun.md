# Delayed EOD Weekend Catch-up and Immediate Recommendation Rerun

## Trigger

Use this when the free/delayed Massive path did not have Friday bars during Friday's scheduled ingest, but the user wants recommendations before the next scheduled market session.

## Key distinction

The safe default Massive end date is the previous business day. On Friday after close this can still resolve to Thursday under the delayed-plan policy; on Saturday/Sunday it resolves to Friday. Therefore, incomplete Friday coverage does **not** mean waiting until the following Friday. Re-probe on the weekend and catch up immediately when Friday bars become authorized.

## Procedure

1. Query per-date price and feature counts for the core universe; do not rely only on `max(dt)` because unrelated backfill symbols can make the database look current.
2. Run a no-write Massive probe on representative core symbols:

```bash
python3 /root/.hermes/scripts/wolfy_eod_after_close_ingest.py \
  --dry-run --tickers SPY,QQQ,IWM,AAPL,MSFT,NVDA,AMZN,META --days 30
```

3. Require every probe symbol's `latest_dates` value to equal the intended Friday/session date.
4. If available, run the five stable shard wrappers rather than one opaque long command. This gives bounded progress and makes retries safe:

```bash
for shard in 1 2 3 4 5; do
  python3 "/root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_${shard}.py"
done
```

5. If the active interpreter lacks the optional PostgreSQL driver, use an ephemeral dependency-capable interpreter rather than changing the host Python installation:

```bash
uvx --with 'psycopg[binary]' python /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_1.py
```

Repeat for the remaining shards. This is a setup fallback, not evidence that the wrappers are permanently broken.
6. Verify the intended session has complete `prices` and `features` coverage against the **exact configured** `CORE_EOD_UNIVERSE` symbol set. Import/read that constant and compare sets; do not assume a historical fixed count (for example, 35) or infer completeness from recent aggregate counts.
7. Check whether a point-in-time universe snapshot already exists for the intended session before signal generation:
   - If it exists, an explicit `--signal-dt YYYY-MM-DD` replay is valid.
   - If it does not exist and this is the normal weekend/current catch-up for the now-latest completed session, first prove `latest_price_date(CORE_EOD_UNIVERSE)` equals the intended session, then run `/root/.hermes/scripts/wolfy_eod_features_signals.py` **without** `--signal-dt`. The normal-current path records the current universe/source availability before breadth and signals.
   - Never manually fabricate or relabel a historical universe snapshot just to make an explicit replay pass. A replay that reports `no point-in-time universe snapshot` is a correct fail-closed outcome.
8. The wrapper invokes deterministic signals, the approved recommendation writer, paper logger, and outcome review. Read back results from Postgres and separate:
   - all research-strategy signals;
   - signals from the explicitly paper-approved strategy;
   - approved recommendation rows;
   - paper trades and `broker_order_submitted` safety flags.
9. Report an actionable paper recommendation only from the approved strategy. If coverage is exact and complete, the strategy is eligible, the run succeeds, and approved-strategy qualifiers are zero, report a verified clean no-trade/cash result. Research signals blocked by strategy status are not recommendations.
10. Validate the emitted `for_session` with the exchange calendar before presenting any entry plan. A weekday-only “next business day” helper can label an exchange holiday as tradable; treat that as a readiness/orchestration defect even when zero recommendations were produced.

## Safety and interpretation

- Never force a recommendation merely because the user wants one quickly.
- Do not broaden or approve a strategy just to increase output frequency.
- Catch-up and deterministic rerun are operational work, not authorization for live orders.
- Keep `no_live_execution=true` and `broker_orders_created=0`.
- A completed cron status is not sufficient proof of date coverage; verify core-symbol rows directly.
- If a long foreground catch-up is interrupted, restart as bounded shard jobs and verify each result instead of declaring failure or telling the user to wait for the next weekly date.