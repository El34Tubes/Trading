# Completing bounded tiered history backfills

Use this when a resumable EOD history backfill must move from “advancing” to a verified terminal state.

## Accounting invariant

Declare the target universe and one history threshold, then use that same threshold in selection, status reporting, and completion checks. For Wolfy’s Massive two-year path the live threshold is normally 495 bars.

Every active/enabled target must land in exactly one terminal class:

```text
targets = depth_ready + current_short + recorded_unavailable + eligible_remaining
```

- `depth_ready`: bars >= threshold.
- `current_short`: bars below threshold but latest date is recent; usually a newly listed or naturally short history. Do not refetch indefinitely.
- `recorded_unavailable`: repeated provider pulls cannot satisfy the target; retain deterministic evidence.
- `eligible_remaining`: no prices, or stale partial history still eligible for another bounded attempt.

Also require feature completeness: every target with prices has features through its latest price date.

## Safe execution sequence

1. Run the Postgres requirements guard and compile the exact global wrapper plus delegated implementation.
2. Capture pre-run counts by tier using `prices` joins; do not assume coverage columns exist on `universe_backfill_targets`.
3. Start or claim the durable task/run row before mutation.
4. Execute bounded batches with an in-run exclusion set, explicit max batches/runtime/failures, and provider-safe pacing.
5. Verify concrete deltas: tickers attempted, ingest/feature run IDs, rows upserted, failures, missing targets, and feature lag.
6. Recompute the accounting invariant with the same threshold used by the runner.
7. Run the exact wrapper again. Completion requires exit 0 and `batches=0`.
8. Close task and run rows only after read-back verification; check for stale `started` runs.

## Repeated provider-limited histories

Do not classify a symbol as unavailable after one transient failure or one short response. Require repeated successful provider calls that return the same stale/sub-threshold history.

When the evidence is repeatable:

- keep the symbol/universe row active so incremental daily ingestion can continue;
- disable only historical backfill (`backfill_enabled=false`);
- append the provider, attempt date, returned bar count, and latest returned date to the durable reason/notes;
- do not call the company delisted or inactive unless an authoritative security-identity source proves that separately;
- count the symbol under `recorded_unavailable`, not `depth_ready` or `current_short`.

This prevents a few permanently unsatisfied targets from consuming every future bounded tick while preserving current-session ingestion.

## Verification SQL shape

Derive coverage from `prices` and feature parity from `features`:

```sql
WITH p AS (
  SELECT ticker, count(*) AS bars, max(dt) AS latest
  FROM prices GROUP BY ticker
), f AS (
  SELECT ticker, max(dt) AS latest
  FROM features GROUP BY ticker
)
SELECT
  count(*) AS targets,
  count(*) FILTER (WHERE p.bars >= :threshold) AS depth_ready,
  count(*) FILTER (
    WHERE p.bars BETWEEN 1 AND :threshold - 1
      AND p.latest >= current_date - interval '5 days'
  ) AS current_short,
  count(*) FILTER (WHERE NOT coalesce(u.backfill_enabled, true)) AS recorded_unavailable,
  count(*) FILTER (
    WHERE coalesce(u.backfill_enabled, true)
      AND (p.ticker IS NULL OR (p.bars < :threshold AND p.latest < current_date - interval '5 days'))
  ) AS eligible_remaining,
  count(*) FILTER (WHERE f.ticker IS NULL OR f.latest < p.latest) AS feature_incomplete
FROM universe_backfill_targets u
LEFT JOIN p ON p.ticker = u.symbol
LEFT JOIN f ON f.ticker = u.symbol
WHERE u.active AND coalesce(u.enabled, true);
```

Bind or substitute the threshold safely for the local SQL tool; do not mix a 400-bar dashboard threshold with a 495-bar runner threshold.

## Completion gate

A backfill card is complete only when:

- `eligible_remaining = 0`;
- `feature_incomplete = 0`;
- every provider-limited target has durable evidence and only historical backfill is disabled;
- all bounded ingest/feature runs are terminal and acceptable;
- an immediate rerun exits successfully with zero batches;
- no live trading, paid-data purchase, or unsupported entitlement override occurred.
