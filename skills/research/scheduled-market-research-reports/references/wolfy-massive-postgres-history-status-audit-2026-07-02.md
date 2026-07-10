# Wolfy Massive → Postgres history status audit (2026-07-02)

Use this pattern when the user asks whether the Massive API two-year history is loaded into Wolfy's Postgres database.

## Scope

This is a read-only status audit, not a backfill. Answer from live Postgres facts and be explicit if the load is partial.

## Connection pitfall

Wolfy's operational Postgres DSN uses the local Unix socket/root role:

```python
DSN = 'dbname=wolfy user=root host=/var/run/postgresql'
```

Do **not** assume TCP/password auth like `user=wolfy password=wolfy host=localhost`; that can fail even when the operational DB is healthy.

## Minimum read-only queries

```sql
-- Overall price coverage
select count(*) from prices;
select count(distinct ticker), min(dt), max(dt) from prices;

-- Bar-count distribution per loaded ticker
select min(c),
       percentile_cont(0.5) within group (order by c),
       max(c),
       count(*) filter (where c >= 500),
       count(*) filter (where c < 500)
from (select ticker, count(*) c from prices group by ticker) s;

-- Shortest histories / obvious partials
select ticker, count(*) c, min(dt), max(dt)
from prices
where ticker not like 'ZZ%'
group by ticker
order by c asc, ticker
limit 20;

-- Features should match price coverage after a proper ingest/recompute
select count(*), count(distinct ticker), min(dt), max(dt) from features;

-- Tiered backfill coverage, using the practical free-tier threshold
with pc as (
  select ticker, count(*) bars, min(dt) first_dt, max(dt) last_dt
  from prices
  group by ticker
)
select coalesce(ubt.wolfy_tier, ubt.tier, '(null)') tier,
       count(*) targets,
       count(pc.ticker) with_prices,
       count(*) filter (where pc.bars >= 495) ge495,
       count(*) filter (where pc.ticker is null) missing,
       min(pc.bars) min_bars,
       percentile_cont(0.5) within group (order by pc.bars) median_bars,
       max(pc.bars) max_bars
from universe_backfill_targets ubt
left join pc on pc.ticker = ubt.symbol
where coalesce(ubt.enabled, ubt.backfill_enabled, true)
group by 1
order by targets desc;

-- Missing target examples, ordered by priority
with pc as (select ticker from prices group by ticker)
select ubt.symbol, coalesce(ubt.wolfy_tier, ubt.tier) tier, ubt.priority, ubt.name
from universe_backfill_targets ubt
left join pc on pc.ticker = ubt.symbol
where coalesce(ubt.enabled, ubt.backfill_enabled, true)
  and pc.ticker is null
order by ubt.priority nulls last, ubt.symbol
limit 30;
```

## Interpretation rules

- Massive free-tier two-calendar-year EOD history may return about **495–501 daily bars**, depending on the market calendar and holidays. Treat `>=495` as practical readiness for this backfill-status question, but still report `>=500` if useful.
- Distinguish **loaded ticker count** from **target universe count**. A full `prices` table may still mean the tiered target universe is only partially loaded.
- Include `features` coverage because a proper EOD ingest should recompute deterministic features alongside prices.
- If only blue-chip/core ETF and part of large-cap are loaded, say "partially loaded" plainly; do not imply mid/small-cap coverage exists.
- Check background processes separately when relevant, but if none are running, say no backfill is currently running.

## Compact answer shape

Use a direct table and short conclusion:

```markdown
Checked live Wolfy Postgres.

Short answer: partially, not fully.

- `prices`: <rows> rows, <tickers> tickers, <min_dt> → <max_dt>
- `features`: <rows> rows, <tickers> tickers, <min_dt> → <max_dt>
- Target universe: <targets> active backfill targets; <with_prices> have prices; <ge495> have practical ~2yr history; <missing> missing

| Tier | Targets | With prices | ≥495 bars | Missing |
|---|---:|---:|---:|---:|
| blue_chip | ... | ... | ... | ... |
| etf_core | ... | ... | ... | ... |
| large_cap | ... | ... | ... | ... |
| mid_cap | ... | ... | ... | ... |
| small_cap | ... | ... | ... | ... |

Conclusion: the Massive two-year history is loaded for <loaded cohorts>, but the full tiered Postgres universe is not finished yet. <Backfill process state if checked.>
```
