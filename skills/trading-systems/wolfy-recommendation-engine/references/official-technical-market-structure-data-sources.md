# Official technical and market-structure data sources

Condensed source-selection and ingestion guidance for extending an EOD equity system beyond daily OHLCV. Verify source pages and terms again at implementation time because endpoints, history, definitions, and licenses can change.

## Classification rules

Keep feature families separate:

- **Technical / market structure:** implied volatility, options volume and put/call ratios, short-sale transaction volume, short-interest positions, breadth, venue/TRF share, fails-to-deliver, futures positioning.
- **Macro risk regime:** Treasury curve, policy rates, credit spreads, and financial-condition/stress indexes. These are not issuer fundamentals, but they are not pure microstructure either.
- **Fundamentals:** earnings, revenue, balance-sheet ratios, valuation, dividends, float, shares outstanding, ownership, and analyst estimates.
- Reference fields needed for joins—CUSIP, ticker history, splits, listing venue, and contract metadata—are not predictive fundamentals.
- If strict technical-only rules exclude issuer reference quantities, use short-interest change and days-to-cover rather than short-interest/float.

## Recommended sources

### Cboe volatility and options sentiment

Official pages:

- VIX history: https://www.cboe.com/tradable-products/vix/vix-historical-data/
- Direct VIX CSV: https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv
- Daily options statistics: https://www.cboe.com/markets/us/options/market-statistics/daily
- Historical options downloads and aggregate ratio links: https://www.cboe.com/us/options/market_statistics/historical_data/

Findings:

- VIX daily history begins in 1990 and is updated daily; this is the simplest high-value addition.
- Daily statistics include total, equity, index, ETP, VIX, and SPX put/call ratios plus volume and open interest.
- Aggregate put/call history is split among current and archive CSVs with changing schemas and definitions. The broad archive begins in 1995, but several linked current files observed during research stopped in 2019 even while the live daily page remained current. Never infer freshness from a filename.
- Cboe describes these public statistics as convenience data, disclaims accuracy, and subjects use to website terms. Public access is not an open-data license. Detailed contract-level history generally points to paid DataShop products.

Implementation: VIX is low difficulty. Put/call backfill is medium difficulty: enumerate official links, inspect actual min/max dates, stitch blocks, record definition breaks, and enforce freshness/gap checks.

### FINRA short-sale volume

Official pages:

- Catalog: https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data
- Definitions and limitations: https://www.finra.org/finra-data/browse-catalog/short-sale-volume
- Daily files: https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data/daily-short-sale-volume-files
- API portal: https://developer.finra.org/

Findings:

- Daily aggregated files and historical selectors cover 2009-present; the interactive display contains the latest 365 days. Monthly files and a Query API are also available.
- This measures short-sale **transactions** reported to FINRA facilities, not outstanding short positions.
- It includes publicly disseminated TRF/ADF/ORF activity and is not consolidated with exchange data. Offsetting buys may be absent. Label features accordingly, e.g. `finra_off_exchange_short_fraction`, never `market_short_ratio`.
- The consolidated NMS daily file is the practical EOD starting point. Monthly transaction archives can be gigabyte-scale and are unnecessary for first implementation.
- FINRA states data is free for non-commercial use, subject to its terms. Reassess before redistribution or commercial use.

Useful features: short/total FINRA-reported volume, short-exempt fraction, rolling z-scores, persistence, and divergence from returns.

### Nasdaq and Cboe short interest

Official pages:

- Nasdaq public short interest: https://www.nasdaqtrader.com/Trader.aspx?id=ShortInterest
- Nasdaq bulk product: https://data.nasdaq.com/databases/NSIR
- Cboe-listed reports: https://www.cboe.com/markets/us/equities/market-statistics/short-interest

Findings:

- Nasdaq short interest is semimonthly, based on mid-month and month-end settlement dates, and disseminated after 4 p.m. ET on scheduled publication dates.
- Public lookup offers rolling per-security history; bulk Nasdaq history/API/SFTP is premium. Bulk history begins around 2007; end-of-month reporting became available in September 2007.
- Cboe publishes free files for Cboe-listed securities, but this is narrow coverage.
- Join by the **public dissemination timestamp**, not the settlement date, to avoid look-ahead bias.
- Do not mix or equate short interest with FINRA daily short-sale volume.

Useful strictly technical features: position change, acceleration, and days-to-cover. Short-interest/float introduces an issuer reference/fundamental denominator.

### Breadth and venue structure

Official pages:

- Nasdaq daily summary: https://www.nasdaqtrader.com/Trader.aspx?id=DailyMarketSummary
- Nasdaq daily market files: https://www.nasdaqtrader.com/Trader.aspx?id=DailyMarketFiles
- Cboe historical market volume: https://www.cboe.com/markets/us/equities/market-statistics/historical-market-volume

Findings:

- A robust, documented, free official exchange API for long-history advance/decline and new-high/new-low series was not identified.
- Prefer deterministic breadth computed from the system's own **point-in-time eligible universe**: advances/declines, new 20-day/52-week highs and lows, percentages above moving averages, up-volume fraction, and equal-weight versus cap-weight divergence.
- Record universe definition, membership effective date, missing observations, unchanged-symbol treatment, adjustment method, and minimum lookback. Current-constituent backfills create survivorship bias.
- Cboe provides daily/monthly market-center and TRF statistics by tape from January 2009: shares, notional, and trade counts. These support venue-share, fragmentation, and average-trade-size regime features but are not breadth.

### Treasury, Federal Reserve, and FRED risk regime

Official pages:

- Treasury daily rates: https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve
- Federal Reserve H.15: https://www.federalreserve.gov/releases/h15/
- FRED API: https://fred.stlouisfed.org/docs/api/fred/
- FRED terms: https://fred.stlouisfed.org/legal/
- Example series: T10Y2Y, DFF, NFCI, STLFSI4, BAMLH0A0HYM2.

Findings:

- Treasury exposes daily par, bill, long-term, and real-yield data with CSV/XML and older archives. Handle tenor-column changes.
- H.15 is posted weekdays at 4:15 p.m. ET except holidays/closures.
- FRED offers series observations and bulk release history; ALFRED vintages should be used where revisions matter.
- Licensing is series-specific. Fed/Treasury-origin series are preferable. Third-party series can be copyrighted; for example, the ICE BofA high-yield OAS page warns of copyright and a reduced rolling history. Keep source and license metadata per series, not merely `source=FRED`.

Useful features: 10y-2y and 10y-3m slope, level/momentum of key tenors, real-yield changes, effective policy rate, NFCI/STLFSI stress levels and changes.

### SEC fails-to-deliver

Official page: https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data

- History begins February 2004.
- First-half files are published at month-end; second-half files around the 15th of the next month.
- Records include settlement date, CUSIP, ticker, issuer, price, and aggregate outstanding fail balance.
- Before September 16, 2008, only balances of at least 10,000 shares were included; model this definition break.
- FTD is an outstanding aggregate balance, not proof of naked shorting and not daily new failures.
- Medium implementation difficulty: zipped pipe files, symbol/CUSIP mapping, lag, and threshold change. Join by availability date.

### CFTC Commitments of Traders

Official page: https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm

- Weekly positioning reports with current, historical-viewable, and compressed-history formats.
- Useful for equity-index futures positioning by leveraged funds and asset managers.
- Treat as a market-regime feature. Account for Tuesday observation versus later publication and format/classification changes.

## Durable ingestion procedure

For each candidate source:

1. Verify the current official landing page and direct endpoint.
2. Download a sample and inspect schema, first/last observation, missing dates, and freshness; do not trust labels such as `current` or `history`.
3. Establish `observation_date`, `published_at`/`available_at`, and `ingested_at` separately.
4. Save raw immutable payloads plus source URL, organization, definition/version, and license class.
5. Write deterministic parsers and definition-break tests.
6. Backtests must require `available_at <= decision_timestamp`; never join lagged data by observation/settlement date alone.
7. Add stale-feed, gap, duplicate, denominator, and extreme-value checks.
8. Keep technical, market-structure, macro-regime, and fundamental feature namespaces separate.
9. Recheck terms before commercial use, redistribution, or exposing raw source data downstream.
