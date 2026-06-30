# Wolfy tiered backfill universe rules

Updated: 2026-06-26

Purpose: create a Massive-backfilled universe that covers blue-chip, mid-cap, and small-cap opportunities without blindly loading every active symbol or polluting Wolfy with SPACs, leveraged products, microcaps, or thin manipulation-prone names.

## Tier model

| Tier | Source seed | Role | Guardrail |
| --- | --- | --- | --- |
| blue_chip | S&P 100 | Core leadership/backtest anchor | Highest liquidity/quality expectation; still requires deterministic signal/risk gates |
| large_cap | S&P 500 excluding blue-chip overlaps | Broad liquid large-cap opportunity set | Use for trend/momentum validation and sector breadth |
| mid_cap | S&P MidCap 400 | Growth/valuation dislocation hunting ground | Require stronger liquidity and volatility checks |
| small_cap | S&P SmallCap 600 | Selective alpha leads | Watch-only until liquidity/manipulation gates pass; smaller risk multiplier |
| etf_core | Wolfy core index/sector/theme ETFs | Regime context and lower single-name risk alternatives | Separate from common-stock cap tiers |

## Explicit exclusions

- Microcaps outside S&P 600.
- SPAC/acquisition/blank-check/unit/warrant/right names.
- ADR/ADS/depositary names unless explicitly approved later.
- Leveraged/inverse/daily reset ETFs.
- Bond/CLO/preferred/note-like products.
- Anything failing active Massive reference status.

## Current selector implementation

Script: `/root/.hermes/wolfy/wolfy_tiered_universe.py`

Tables/columns added non-destructively:

- `universe_tier_rules`
- `universe_backfill_targets`
- `universe_symbols.wolfy_tier`
- `universe_symbols.tier_source`
- `universe_symbols.backfill_priority`
- `universe_symbols.backfill_enabled`
- `universe_symbols.tier_notes`

Current selected targets after risk filters:

| Tier | Targets |
| --- | ---: |
| blue_chip | 92 |
| large_cap | 358 |
| mid_cap | 360 |
| small_cap | 531 |
| etf_core | 15 |
| total | 1,356 |

## Backfill state after initial run

Loaded with full Massive free-tier two-year adjusted EOD history:

- blue_chip: complete, 92/92 loaded
- etf_core: complete, 15/15 loaded
- large_cap: pending, 0/358 loaded
- mid_cap: pending, 0/360 loaded
- small_cap: pending, 0/531 loaded

Massive free-tier behavior remains about 501 daily bars per ticker, typically 2024-06-26 through 2026-06-25 for new symbols, plus existing incremental current bars where available.

## Batch rule

Backfill in small resumable batches, not one massive request:

```bash
cd /root/.hermes/wolfy
TICKERS=$(psql -d wolfy -Atc "select string_agg(symbol,',' order by priority) from (select t.symbol,t.priority from universe_backfill_targets t left join (select distinct ticker from prices) p on p.ticker=t.symbol where t.active and t.tier='large_cap' and p.ticker is null order by t.priority limit 10) s")
uvx --with 'psycopg[binary]' python eod_price_features.py --source massive --tickers "$TICKERS" --days 730 --min-history-bars 500 --pause-seconds 1.0 --no-validate
```

Use `limit 5-10` for reliability. The earlier one-shot 75-ticker run timed out before commit; small chunks committed cleanly.
