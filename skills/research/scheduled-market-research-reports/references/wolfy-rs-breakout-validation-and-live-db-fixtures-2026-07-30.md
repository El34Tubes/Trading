# Wolfy RS breakout validation failure and live-DB test isolation — 2026-07-30

## Context

During implementation of Wolfy's first options-focused recommendation strategy, `liquid_rs_breakout_continuation`, the strategy was built with TDD and then validated against Postgres EOD data.

## Durable lessons

### 1. Do not advance the recommendation writer before validation gates

The strategy implementation can be technically correct and still fail as a trading model. After generating historical research signals and running the OOS backtest, the strategy remained `research_only` and must not produce recommendations.

Validation result from this session:

| Metric | Result |
|---|---:|
| Historical signals | 12,299 |
| Backtest ID | 84 |
| Trades | 12,270 |
| IS trades | 10,607 |
| OOS trades | 1,663 |
| IS Sharpe | -0.4146 |
| OOS Sharpe | 0.6503 |
| OOS CAGR | 0.2311 |
| Max drawdown | -1.0000 |
| Gate verdict | failed |

Failure reasons:

- `oos_sharpe_below_threshold` — user gate is OOS Sharpe >= 0.75.
- `max_drawdown_exceeds_threshold` — user gate is max drawdown < 15%.

Correct outcome:

- Keep `strategies.status='research_only'`.
- Do not promote to `candidate`.
- Do not create actionable recommendations or paper trades.
- Queue a rule-revision task before recommendation-writer work.

### 2. Validate the actual holding/exit design, not just next-close returns

The first backtest used the existing close-to-next-close return loader. For an options-timed 1–2 week strategy, the next revision should test the strategy's actual rules:

- 10-trading-day max hold,
- stop below prior 5-day low,
- partial/target at 1.5R,
- trailing remainder,
- no chase if next open is >0.5 ATR beyond trigger,
- market-regime handling,
- ranking only the best setups rather than taking every qualifying breakout.

A failing next-close backtest is useful as a hard gate, but it is not the final design evaluation.

### 3. Live Postgres tests need fixture isolation

A test used synthetic tickers but a real-looking 2026 signal date. Because the code correctly writes to the shared Wolfy Postgres DB, those fixture rows appeared as real historical strategy signals until cleaned.

For Wolfy tests that touch shared Postgres:

1. Prefer ephemeral DBs or transaction rollbacks when possible.
2. Use synthetic ticker prefixes such as `ZZ...`.
3. Use far-future dates such as `2099-*` so fixture rows cannot collide with market history.
4. Cleanup every table the flow may touch:
   - `setups`
   - `signals`
   - `earnings_calendar`
   - `features`
   - `prices`
   - `universe_symbols`
5. Before running historical validation, check and remove only rows matching known synthetic fixture markers/dates.

### 4. SPY benchmark data is a prerequisite for RS strategies

`liquid_rs_breakout_continuation` requires 20-day relative strength vs SPY. If SPY bars are missing, signal generation will produce no real strategy history even when target tickers have data.

Before RS validation:

```bash
psql -d wolfy -X -A -F $'\t' -c "select ticker,min(dt),max(dt),count(*) from prices where ticker='SPY' group by ticker;"
```

If missing, ingest SPY with the normal EOD wrapper rather than faking benchmark data:

```bash
/root/.hermes/scripts/wolfy_eod_after_close_ingest.py --tickers SPY --days 800 --source massive
```

## Next revision task shape

Queue/execute a deterministic rule-revision task before enabling recommendations:

- Add true 10-day stop/target/timeout backtest support.
- Add/compare market regime hard or conditional filters.
- Add rank/top-N selection before validation.
- Separate ETF vs single-stock thresholds if needed.
- Keep strategy `research_only` until OOS passes and user approves.
