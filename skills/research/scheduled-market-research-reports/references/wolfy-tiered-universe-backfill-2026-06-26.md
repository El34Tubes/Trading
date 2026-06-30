# Wolfy tiered universe + cautious backfill pattern (2026-06-26)

Use this when expanding Wolfy's EOD universe beyond a small core list while preserving the user's manipulation-risk, liquidity, Robinhood, and EOD-only constraints.

## Durable pattern

Segment the equity/ETF universe before backfilling or scoring. Do not treat blue chips, mid caps, and small caps as one homogeneous pool.

Recommended tier shape:

| Tier | Seed/source idea | Purpose | Default handling |
| --- | --- | --- | --- |
| `blue_chip` | S&P 100 / highest-quality liquid leaders | Core leadership and safer initial expansion | Backfill first; lower operational risk |
| `large_cap` | S&P 500 excluding blue-chip overlaps | Broad institutional opportunity set | Backfill after blue chips |
| `mid_cap` | S&P MidCap 400 | Growth/valuation dislocation pool | Backfill after large caps; require liquidity/risk gates |
| `small_cap` | S&P SmallCap 600 | Selective alpha leads | Backfill last; stricter liquidity/manipulation filters |
| `etf_core` | Core index/sector/regime ETFs | Benchmarks, regime, sector rotation, lower single-name risk | Keep always loaded/fresh |

## Exclusions to bake into selectors

Exclude by default unless the user explicitly changes scope:

- Microcaps outside S&P 600 or equivalent quality/liquidity screen.
- SPACs, acquisition companies, blank-check names.
- Warrants, rights, units, preferreds, notes, and non-common-share instruments.
- ADR/ADS/depositary names when the user is avoiding international/government-interference/manipulation risk.
- Leveraged, inverse, and daily-reset ETFs.
- Bond/CLO/preferred/note products when the task is U.S. stock/ETF swing research.
- Inactive/reference-stale symbols from the market-data provider.

## Database/selector shape

A useful Postgres pattern is:

- Add tier metadata to `universe_symbols`: `wolfy_tier`, `tier_source`, `backfill_priority`, `backfill_enabled`, `tier_notes`.
- Track rules in `universe_tier_rules`.
- Track load state in `universe_backfill_targets` so backfills are resumable and auditable.
- Keep ETF core separately identifiable from equity tiers.

## Backfill operations

For Massive/Polygon free-tier EOD aggregates, verify actual returned/stored depth rather than requested lookback. Free-tier history may cap around two years / ~501 daily bars.

Use small resumable chunks:

1. Backfill `blue_chip` first.
2. Then `large_cap` in about 10-symbol chunks.
3. Then `mid_cap` in about 10-symbol chunks.
4. Then `small_cap` in 5-10 symbol chunks with stricter liquidity/risk checks.

Avoid one-shot 50-100+ symbol foreground runs: they can time out before commit and lose the batch. Prefer resumable scripts/tables and verify each committed chunk.

After each chunk, verify:

- `prices` and `features` ticker counts/date range/bar-count distribution.
- Tier target counts vs loaded counts.
- Latest `dt` alignment between `prices`, `features`, and generated `signals`.
- Regression tests or smoke tests for selector/ingest behavior.

## Reporting to the user

Report tier expansion as concrete state, not broad promises:

- Tier counts selected.
- Tier counts loaded.
- Current `prices/features` date range and median bars.
- Tests/smoke output.
- Next exact chunk order.

Keep setup signals non-actionable unless they pass the existing Hermes-EOD approved-strategy and risk gates.