# Wolfy data-load status audit pattern — 2026-06-27

Use when the user asks whether Wolfy “loaded the data” or asks for data-load progress after tiered EOD universe expansion.

## What worked

Start with the deterministic visible ledger, then verify tier coverage directly in Postgres:

```bash
python3 /root/.hermes/wolfy/visible_progress_ledger.py --json
```

Then query the operational Postgres source of truth:

```sql
select 'prices|'||count(*)||'|'||count(distinct ticker)||'|'||min(dt)||'|'||max(dt) from prices;
select 'features|'||count(*)||'|'||count(distinct ticker)||'|'||min(dt)||'|'||max(dt) from features;
select 'signals|'||count(*)||'|'||count(distinct ticker)||'|'||min(dt)||'|'||max(dt) from signals;
select 'setups|'||count(*) from setups;
```

For tier coverage, do not assume a table named `universe`; the current schema uses `universe_symbols`, `universe_backfill_targets`, and `universe_tier_rules`:

```sql
with latest as (
  select ticker, count(*) bars, max(dt) last_dt
  from prices
  group by ticker
)
select
  t.tier,
  count(*) targets,
  count(l.ticker) loaded,
  count(*) filter (where l.bars >= 500) ge500,
  min(l.bars) min_bars,
  percentile_cont(0.5) within group (order by l.bars) median_bars,
  max(l.bars) max_bars,
  max(l.last_dt) latest_dt
from universe_backfill_targets t
left join latest l on l.ticker = t.symbol
where t.active
group by t.tier
order by case t.tier
  when 'blue_chip' then 1
  when 'etf_core' then 2
  when 'large_cap' then 3
  when 'mid_cap' then 4
  when 'small_cap' then 5
  else 9
end;
```

## Answer shape

Give a compact, honest partial-completion table:

- prices/features/signals/setups row counts and freshness.
- tier targets vs loaded vs >=500 bars.
- explicitly distinguish loaded foundation from unfinished expanded tiers.
- if strategies are still `research_only`, say no actionable setups were created because the approved-strategy gate blocks them.

Example conclusion:

> Yes — the blue-chip and ETF foundation is loaded, and large-cap backfill has started, but the full expanded universe is not done yet. Mid/small caps are still unloaded. No actionable setups exist because strategies remain research_only / not human-approved.

## Pitfalls

- A `relation "universe" does not exist` error is not a DB failure; switch to the current tier tables listed above.
- `universe_backfill_targets` uses `active`, not `enabled`; `universe_symbols` uses `backfill_enabled`.
- Do not treat a latest-date partial update as complete broad coverage. Compare latest full broad date against latest partial date and report partial freshness honestly.
- If a background backfill log exists but no process is running, summarize the current DB state rather than implying the run completed. Check logs only as provenance; DB counts are the answer.
