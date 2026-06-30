# Wolfy Massive API data plan

Source docs scraped/inspected: https://massive.com/docs

Focus areas per user direction: stocks, options, indices, and option-related data only. Crypto, forex, futures, and alternative data are out of scope for Wolfy unless explicitly requested later.

## Current free-tier finding

A live request for SPY daily adjusted aggregates from 2018-01-01 through 2026-06-26 returned:

- status: DELAYED
- resultsCount: 501
- first returned bar: 2024-06-26
- last returned bar: 2026-06-25

Operational conclusion: the current Massive key appears limited to roughly two years / ~501 daily bars for aggregate history. Wolfy should not assume five-plus years are available from Massive free tier. The backtesting baseline should use the currently available two-year daily window unless a paid tier or a different historical source is added.

## REST endpoints worth integrating

### Stocks

Primary for Wolfy EOD/backtesting:

- All tickers: https://massive.com/docs/rest/stocks/tickers/all-tickers
- Ticker overview: https://massive.com/docs/rest/stocks/tickers/ticker-overview
- Ticker types: https://massive.com/docs/rest/stocks/tickers/ticker-types
- Aggregate Bars (OHLC): https://massive.com/docs/rest/stocks/aggregates/custom-bars
- Daily Market Summary: https://massive.com/docs/rest/stocks/aggregates/daily-market-summary
- Daily Ticker Summary: https://massive.com/docs/rest/stocks/aggregates/daily-ticker-summary
- Previous Day Bar: https://massive.com/docs/rest/stocks/aggregates/previous-day-bar
- Splits: https://massive.com/docs/rest/stocks/corporate-actions/splits
- Dividends: https://massive.com/docs/rest/stocks/corporate-actions/dividends
- Market Holidays / Status: https://massive.com/docs/rest/stocks/market-operations/market-holidays and /market-status

Secondary useful context, not signal-critical until access is confirmed:

- Full/Unified market snapshots
- Top market movers
- Fundamentals: balance sheets, cash flow, income statements, ratios, short interest, short volume, float
- Filings/risk factors/news

### Options

Primary for defined-risk option research and liquidity checks:

- All contracts: https://massive.com/docs/rest/options/contracts/all-contracts
- Contract overview: https://massive.com/docs/rest/options/contracts/contract-overview
- Option Chain Snapshot: https://massive.com/docs/rest/options/snapshots/option-chain-snapshot
- Option Contract Snapshot: https://massive.com/docs/rest/options/snapshots/option-contract-snapshot
- Aggregate Bars (OHLC): https://massive.com/docs/rest/options/aggregates/custom-bars
- Daily Ticker Summary: https://massive.com/docs/rest/options/aggregates/daily-ticker-summary
- Previous Day Bar: https://massive.com/docs/rest/options/aggregates/previous-day-bar
- Quotes/trades only if needed for spread/liquidity validation and rate limits allow it

Wolfy rule: use options data for structure/liquidity/risk validation only. Do not create auto-execution. Keep human-gated.

### Indices

Primary for regime and benchmark context:

- All tickers: https://massive.com/docs/rest/indices/tickers/all-tickers
- Ticker overview: https://massive.com/docs/rest/indices/tickers/ticker-overview
- Aggregate Bars (OHLC): https://massive.com/docs/rest/indices/aggregates/custom-bars
- Previous Day Bar: https://massive.com/docs/rest/indices/aggregates/previous-day-bar
- Daily Ticker Summary: https://massive.com/docs/rest/indices/aggregates/daily-ticker-summary
- Indices snapshot / unified snapshot
- Market holidays / market status

## Implementation priority

1. Keep stock adjusted daily aggregates as the primary EOD price source.
2. Use stock reference tickers to maintain a Robinhood-tradable/liquid U.S. stocks + ETF universe cache.
3. Use splits/dividends for data-quality review around recent corporate actions.
4. Add indices aggregates for regime validation if the current key allows access.
5. Add options contract chain snapshots only for candidate tickers, capped per run, to avoid free-tier overuse.
6. Keep EODHS/EODHD as a capped fallback/cross-check source, not bulk primary ingest.

## Rate-limit/free-tier rules

- Never bulk-refresh all tickers daily.
- Bootstrap only bounded universes; use incremental missing-day fetches afterward.
- Keep options-chain requests candidate-only, not universe-wide.
- Store raw responses/derived rows in Postgres so backtests reuse cached data.
- If a request returns DELAYED or a shorter historical window than requested, record that as source coverage, not as a pipeline failure.
