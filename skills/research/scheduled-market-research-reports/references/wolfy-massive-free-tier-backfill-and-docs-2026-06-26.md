# Wolfy Massive free-tier backfill and docs focus — 2026-06-26

## Trigger

User asked for a one-time Massive API historical pull to load data for backtesting, then clarified that only Massive docs for stocks, options, indices, and options-related data are worth focusing on.

## Durable findings

- Wolfy's active price path should continue to prefer Massive adjusted daily EOD aggregates for stocks/ETFs.
- Massive free-tier aggregate history may return a shorter range than requested. In this session, a live SPY request for 2018-01-01 through 2026-06-26 returned only ~501 daily bars, first bar 2024-06-26 and last bar 2026-06-25, with `status=DELAYED`.
- Treat shorter returned history as source coverage information, not as a failed ingest, when HTTP status/payload are otherwise valid.
- For backtesting, verify actual stored depth after ingest (`min(dt)`, `max(dt)`, bars per ticker), not requested lookback days.
- System `python3` may lack `psycopg`; use `uvx --with 'psycopg[binary]' python ...` for manual Wolfy Postgres scripts if needed. This is the fix pattern, not a durable claim that system Python is broken.

## Backfill pattern used

For a bounded universe, force bootstrap by setting `--min-history-bars` higher than current stored bars and include a per-ticker pause:

```bash
cd /root/.hermes/wolfy
TICKERS='SPY,QQQ,IWM,DIA,XLK,XLF,XLY,XLI,XLE,XLV,XLP,XLU,XLB,XLRE,XLC,AAPL,MSFT,NVDA,AMZN,GOOGL,META,TSLA,AVGO,JPM,LLY,V,UNH,COST,NFLX,AMD,ORCL,CRM,PANW,SMH'
uvx --with 'psycopg[binary]' python eod_price_features.py \
  --source massive \
  --tickers "$TICKERS" \
  --days 1825 \
  --min-history-bars 1250 \
  --pause-seconds 1.5 \
  --no-validate
```

Notes:

- `--no-validate` avoids extra corporate-action calls during a bulk historical pull; run quality validation separately if needed.
- Keep EODHS fallback disabled for bulk (`--eodhs-fallback-max-tickers 0`); use it only for capped spot checks.
- After backfill, recompute features and regenerate deterministic signals for the latest stored date before treating backtests as current.

## Verification queries

```sql
select 'prices', count(distinct ticker), min(first_dt), max(last_dt), min(c), percentile_cont(0.5) within group (order by c), max(c), sum(c)
from (
  select ticker, min(dt) first_dt, max(dt) last_dt, count(*) c
  from prices
  group by ticker
) s;

select 'features', count(distinct ticker), min(first_dt), max(last_dt), min(c), percentile_cont(0.5) within group (order by c), max(c), sum(c)
from (
  select ticker, min(dt) first_dt, max(dt) last_dt, count(*) c
  from features
  group by ticker
) s;

select st.name, st.status, count(s.*), min(s.dt), max(s.dt)
from strategies st
left join signals s on s.strategy_id=st.id
group by st.name, st.status
order by st.name;
```

## Massive docs scope for Wolfy

Only prioritize:

- Stocks: tickers, ticker overview/types, adjusted aggregate OHLC bars, daily summaries, previous day bar, splits, dividends, market holidays/status, fundamentals/filings only after access is confirmed.
- Options: contracts, contract overview, option-chain snapshot, contract snapshot, option OHLC/daily summaries, quotes/trades only for candidate-level liquidity/spread validation.
- Indices: tickers, overview, aggregate OHLC, previous day/daily summaries, snapshots, market holidays/status.

Do not spend Wolfy build time on Massive crypto, forex, futures, or broad alternative-data docs unless the user explicitly changes scope.

## Wolfy interpretation

- Current two-year Massive free-tier history is enough for initial EOD walk-forward smoke/backtests, but not robust multi-cycle strategy validation.
- If deeper multi-cycle backtests are required, recommend either a higher Massive tier or an additional historical EOD source for older daily bars, while keeping Massive as current/incremental primary.
- Do not imply actionable/capital setups from regenerated signals while strategies remain `research_only` or `candidate`; approved-strategy gate still controls setup creation.
