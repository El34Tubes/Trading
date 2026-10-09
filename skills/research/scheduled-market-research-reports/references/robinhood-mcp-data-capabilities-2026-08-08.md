# Robinhood MCP / API Data Capabilities for Wolfy

Session research: user asked whether connecting a Robinhood MCP server would help the Wolfy paper-recommendation goal, specifically whether it can provide historical open/close stock history and other useful strategy data.

## Historical stock OHLCV

Robinhood’s historicals endpoint can return stock/ETF OHLCV:

```text
https://api.robinhood.com/quotes/historicals/?symbols=AAPL&interval=day&span=5year&bounds=regular
```

Observed fields:

- `begins_at`
- `open_price`
- `close_price`
- `high_price`
- `low_price`
- `volume`
- `session`
- `interpolated`
- `symbol`

Supported values from `robin_stocks`:

- `interval`: `5minute`, `10minute`, `hour`, `day`, `week`
- `span`: `day`, `week`, `month`, `3month`, `year`, `5year`
- `bounds`: `regular`, `trading`, `extended`

Important limitation: `extended` / `trading` bounds only work with `span=day`. Use Robinhood historicals as supplemental/spot-check data, not Wolfy’s canonical backtest store; keep Massive/Postgres as canonical for deterministic validation.

## Other useful Robinhood data

Quotes can provide:

- bid/ask prices and sizes
- last trade and extended-hours prices
- previous/adjusted previous close
- trading halt flag
- instrument/state metadata

Fundamentals can provide:

- current open/high/low/volume
- average volume / 2-week / 30-day average volume
- 52-week high/low and dates
- market cap, float, shares outstanding
- P/E, P/B, dividend yield
- sector, industry, description

Other available surfaces in common Robinhood wrappers/MCPs:

- analyst ratings
- news
- earnings
- splits/dividends
- market hours
- options chains, expirations, strikes
- option market data: bid/ask/mark, IV/Greeks/open interest/volume where exposed
- option historicals
- account/portfolio/positions/buying power/order history for read-only context

## Architecture guidance for Wolfy

Use Robinhood MCP as a read-only broker/tradability/options enrichment adapter after deterministic Wolfy signals are already created:

```text
Wolfy deterministic signal
  -> Postgres recommendation row
  -> Robinhood read-only enrichment
  -> tradability/options/account-position warnings
  -> paper-trade logger / daily summary
```

Do **not** let Robinhood decide trades or replace deterministic strategy validation.

Recommended first integration mode:

- read-only only
- no order placement tools
- no cancel/order/write/account-setting tools
- no money movement
- no live execution

Good candidate MCP style: read-only servers such as `verygoodplugins/robinhood-mcp`, which advertises tools like portfolio, positions, quote, historicals, and options positions. Be more cautious with MCP/CLI projects that expose trading/write tools; if used, hard-disable live writes and wrap them behind explicit human approval gates.

## Strategy relevance

For the current RS-breakout/options paper-testing path, Robinhood’s highest-value data is:

- current tradability and halt state
- bid/ask sanity checks
- current/extended-hours movement
- option chain availability for 2–3 week call-spread structure
- option bid/ask/IV/Greeks/open interest as advisory metadata
- existing account positions to avoid duplicate exposure warnings

Stock OHLCV from Robinhood can help with recent fallback/backfill or validation spot-checks, but should not supersede the canonical Postgres EOD history used for setup-outcome validation.
