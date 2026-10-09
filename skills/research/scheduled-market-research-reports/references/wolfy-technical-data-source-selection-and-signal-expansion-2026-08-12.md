# Wolfy technical-data source selection and signal expansion (2026-08-12)

Use this reference when reviewing technical-only data sources or deciding which signals to add to Wolfy's deterministic EOD strategy.

## Current production lineage

- Canonical source: Massive adjusted daily aggregates (`massive-adjusted-eod`).
- Stored flow: Massive aggregate `v` -> Postgres `prices.volume` -> 20-session `features.vol_ratio` -> deterministic signal gate.
- Configured fallback: EODHD/EOD Historical Data, capped for small missing-ticker/cross-check pulls.
- Yahoo chart data is suitable only for smoke/emergency validation, not canonical production history.
- Robinhood MCP is read-only broker enrichment (tradability, quotes, spread, options/account context), not historical alpha or canonical OHLCV.
- Observed production coverage at review time: 1,278 tickers, 632,751 bars, 2024-06-18 through 2026-08-11, median 501 bars, 1,237 tickers with at least 495 bars.

## Source-selection rule

Do not buy vendor-computed RSI, MACD, ADX, Bollinger Bands, ATR, moving averages, or similar indicators. Compute price-derived indicators locally from canonical raw bars. A new paid source is worthwhile only when it adds an orthogonal dataset, materially deeper history, better provenance/corporate-action handling, or execution-quality context.

## Recommended order

1. **Free local features from existing OHLCV**
   - Breadth: percent above 20/50/200DMA, advance/decline, new highs-minus-lows.
   - Relative strength: 5/20/63/126-day excess returns versus SPY and sector ETF.
   - Setup quality: ATR percentile, Bollinger-width percentile, close-location value, upper-wick ratio, breakout extension in ATR, base depth.
   - Volume quality: volume percentile, up/down-volume ratio, OBV slope, accumulation/distribution, liquidity stability.
   - Trend quality: MA slope, regression slope/R², ADX.
2. **Free official regime data**
   - Cboe VIX/VVIX/VIX9D history.
   - Cboe daily total/equity/index/ETF/SPX put-call statistics and call/put volume/OI.
   - Treat as soft regime features until chronological OOS validation proves a hard gate.
3. **Deeper adjusted EOD history (~$30/month)**
   - Tiingo Power: best value for deep adjusted EOD validation; published 30+ years, raw and CRSP-style adjusted prices, high paid request limits.
   - Massive Starter: lowest integration friction; published 5 years, unlimited calls, delayed aggregates/flat files/corporate actions.
   - Prefer Tiingo when regime depth matters; prefer Massive Starter when implementation simplicity matters.
4. **Experimental free market-structure data**
   - FINRA daily short-sale volume: research feature only; it is not short interest and is affected by market-making/execution mechanics.
   - Nasdaq short interest: twice monthly and useful for setup classification, not entry timing.
5. **Historical options only after underlying strategy success**
   - Current Robinhood options data is enough for read-only expression/liquidity context.
   - Historical IV, skew, term structure, put-call, and volume/OI may be evaluated later; they must not originate an equity signal before validation.

## Vendor notes verified during the review

- Massive Basic: $0, 5 calls/minute, 2 years, EOD, all U.S. stock tickers, stated 100% market coverage, corporate actions and aggregates.
- Massive Starter: $29/month, unlimited calls, 5 years, 15-minute delayed data.
- Massive Developer: $79/month, 10 years.
- Massive Advanced: $199/month, 20+ years and real time.
- Tiingo Starter: $0, 500 unique symbols/month, 50 requests/hour, 1,000/day; published 30+ years EOD history.
- Tiingo Power: $30/month or $300/year, broad symbol access, 10,000 requests/hour, 100,000/day, 40 GB/month.
- Alpha Vantage free: 25 requests/day. Lowest premium tier observed: $49.99/month for 75 requests/minute and EOD options data.
- Finnhub free: 60 calls/minute and published 30+ years U.S. OHLC; useful as a cross-check, not first canonical choice.
- Marketstack Basic: $9.99/month and up to 10 years; mostly duplicate OHLCV.
- Twelve Data Basic: 8 API credits/minute and 800/day; too constrained for broad daily refresh.
- Alpaca free live stock feed is IEX-only. Do not mix IEX-only volume with consolidated-volume history. Historical SIP requests old enough to clear the recency restriction may be available, but validate plan/license before relying on them.
- Yahoo/yfinance and Stooq are research/smoke cross-checks, not preferred canonical production sources.

Pricing and limits change. Recheck official provider pages before purchase or implementation.

## Technical strategy-expansion discipline

- Add one feature family at a time and compare chronological OOS setup outcomes against the approved baseline.
- Do not combine many correlated transforms of close price and call the result diversification.
- Prefer orthogonal confirmation: breadth + sector RS + volatility contraction + breakout close quality + market volatility/options regime.
- Keep new variants `research_only` until setup-outcome gates pass; only same-gate passers may auto-activate for paper recommendations under the user's existing policy.
- Quiet/no-setup outcomes remain valid.

## Provenance requirement before mixing vendors

The current `prices` primary key is `(ticker, dt)` and does not identify a source per row. Before introducing a second canonical bar vendor, add source-aware persistence such as:

- `source`
- `adjustment_basis`
- `ingested_at`
- `source_run_id`

A canonical signal run must use one coherent source and adjustment basis. Cross-check data must not silently overwrite canonical rows.

## Official references

- Massive pricing: https://massive.com/pricing?product=stocks
- Massive aggregate bars: https://massive.com/docs/rest/stocks/aggregates/custom-bars
- Tiingo pricing: https://www.tiingo.com/about/pricing
- Tiingo EOD docs: https://www.tiingo.com/documentation/end-of-day
- Cboe VIX history: https://www.cboe.com/tradable-products/vix/vix-historical-data
- Cboe daily options statistics: https://www.cboe.com/markets/us/options/market-statistics/daily
- FINRA short-sale volume catalog: https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data
- Nasdaq short interest: https://www.nasdaqtrader.com/Trader.aspx?id=ShortInterest
- FRED API: https://fred.stlouisfed.org/docs/api/fred/
- Alpaca market-data FAQ: https://docs.alpaca.markets/docs/market-data-faq
