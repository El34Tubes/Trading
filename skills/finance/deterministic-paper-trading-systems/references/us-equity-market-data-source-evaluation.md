# U.S. equity market-data source evaluation

Use this reference when comparing free or low-cost OHLCV sources for technical-signal pipelines. Re-check live official pages before making purchase or architecture decisions; pricing and entitlements change.

## Evidence checklist

For each provider, capture:

- official/free price and request limits;
- whether the limit applies to the platform or specifically to the stock-price dataset;
- daily and intraday history depth;
- U.S. exchange coverage and whether the feed is single-venue, delayed consolidated, or SIP;
- raw versus split/dividend/spin-off-adjusted OHLC and volume;
- separate corporate-action endpoints and symbol-change handling;
- survivorship/delisted-symbol characteristics;
- personal/commercial use, redistribution, retention, and derived-data rights;
- operational traits: official API, authentication, SLA, anti-bot behavior, silent revisions;
- bounded signal role: canonical, fallback, validation, or research only.

## Provider caveats observed in August 2026

### Alpaca Market Data

- Official Trading API documentation listed Basic as free and Algo Trader Plus as paid.
- Basic equities used IEX; detailed docs described IEX as a single venue with roughly 2.5% of market volume. Paid SIP covered all U.S. exchanges.
- Historical bars supported explicit `raw`, `split`, `dividend`, `spin-off`, and `all` adjustment choices; split adjustment covered price and volume.
- Strong candidate for a licensed secondary feed, but IEX bars should not validate consolidated volume, exact highs/lows, gaps, liquidity, or execution-sensitive signals.
- Sources: https://docs.alpaca.markets/docs/about-market-data-api ; https://docs.alpaca.markets/docs/historical-stock-data-1 ; https://docs.alpaca.markets/reference/stockbars

### Nasdaq Data Link

- Do not confuse authenticated free Tables API quotas with free entitlement to U.S. equity EOD data.
- Current catalog documentation identified QuoteMedia End of Day U.S. Prices as premium; endpoint metadata also marked the table premium.
- Old examples for a generic free `EOD` database may be stale. Verify the exact product code and entitlement.
- Sources: https://docs.data.nasdaq.com/docs/rate-limits-1 ; https://docs.data.nasdaq.com/docs/data-organization ; https://data.nasdaq.com/api/v3/datatables/QUOTEMEDIA/PRICES/metadata.json

### Stooq

- Provides broad downloadable historical files, including U.S. Nasdaq/NYSE/NYSE MKT groups and several intervals.
- Official pages state personal use only and prohibit commercial use.
- Adjustment semantics were not documented clearly enough to assume raw, split-adjusted, or total-return treatment. Reconcile known split/dividend dates before use.
- Browser proof-of-work and direct-download denial are operational concerns, not proof that the service is permanently unavailable. Treat it as a research/validation source without an API SLA.
- Source: https://stooq.com/db/h/

### Yahoo Finance / yfinance

- `yfinance` is unofficial and its own documentation points users to Yahoo terms and personal-use restrictions.
- It supports `auto_adjust`, `back_adjust`, `actions`, and `repair`; intraday depth is constrained while daily `max` is instrument-dependent.
- No stable official yfinance quota exists. Yahoo terms reserve discretionary rate limiting.
- Useful for asynchronous cross-checks and corporate-action reconciliation, not unattended canonical ingestion.
- Sources: https://ranaroussi.github.io/yfinance/ ; https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html ; https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apiforydn/index.html

### Finnhub

- Distinguish the free account quota from Stock Candles entitlement: the candles documentation marked the endpoint as premium at review time.
- Official pricing was rendered client-side; the public page's embedded state and shipped bundle exposed plan prices, calls/minute, history depths, billing frequency, and personal-use wording.
- Candle samples exposed OHLCV but did not establish adjustment semantics. Separate split/dividend endpoints are not proof that candle bars are adjusted.
- Confirm venue consolidation, corporate-action normalization, retention of downloaded/derived data, and permitted use before selection.
- Sources: https://finnhub.io/pricing ; https://finnhub.io/docs/api/stock-candles ; https://finnhub.io/terms-of-service

## Signal-role rules

- **Price-only slow indicators:** a single-venue feed can be a rough sanity check for liquid names, not an exact reference.
- **Volume, relative volume, dollar volume, gaps, high/low breakouts, liquidity, or execution:** require consolidated coverage or explicitly accept venue bias.
- **Adjusted trend indicators:** freeze an adjustment policy and verify OHLC plus volume around forward/reverse splits and cash dividends.
- **Fallback ingestion:** preserve provider, feed, adjustment mode, retrieval time, and original payload provenance. Never merge fallback rows invisibly into canonical history.
