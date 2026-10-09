# Robinhood MCP broker enrichment for Wolfy paper recommendations — 2026-08

## Class-level lesson

Robinhood MCP is valuable for broker-side enrichment, not as the source of trade decisions. Keep Wolfy's deterministic Postgres EOD strategy path canonical, then attach Robinhood read-only data to approved paper recommendations for tradability, quote, option-spread, exposure, and event-risk context.

## Implemented Wolfy-side pattern

`/root/.hermes/wolfy/eod_signals.py` now supports:

```python
write_approved_paper_recommendations(
    conn,
    *,
    signal_dt,
    tickers=None,
    max_recommendations=3,
    risk_fraction=Decimal("0.05"),
    dry_run=False,
    broker_enrichment=None,
)
```

`broker_enrichment` is a ticker-keyed mapping produced from read-only Robinhood data. It is persisted into `recommendations.notes` without creating broker orders.

Stored note fields include:

- `broker_enrichment`
- `broker_warnings`
- `robinhood_read_only=true`
- `broker_order_submitted=false`
- `equity_fallback` based on option-spread availability

Normalized warnings/checks include:

- halted/not tradable
- price drift from EOD baseline
- wide bid/ask spread
- existing equity exposure
- existing option exposure
- open order warning
- earnings inside expected hold window
- option-spread availability
- fundamentals payload passthrough

`log_approved_paper_recommendation_trades` carries broker enrichment and warnings forward into `paper_trades.notes` while preserving `broker_order_submitted=false`.

## Read-only adapter

`/root/.hermes/wolfy/robinhood_broker_enrichment.py` defines the safe payload contract and explicit tool separation.

Read-only Robinhood MCP tools expected for enrichment:

- `get_accounts`
- `get_portfolio`
- `get_equity_positions`
- `get_option_positions`
- `get_equity_orders`
- `get_option_orders`
- `get_equity_quotes`
- `get_equity_price_book`
- `get_equity_historicals`
- `get_equity_fundamentals`
- `get_equity_tradability`
- `get_financials`
- `get_earnings_calendar`
- `get_earnings_results`
- `get_option_chains`
- `get_option_instruments`
- `get_option_quotes`
- `get_option_historicals`

Live-action tools remain blocked unless the user gives explicit current-session live-trading authorization:

- `place_equity_order`
- `place_option_order`
- `cancel_equity_order`
- `cancel_option_order`
- `exercise_option`
- `cancel_option_exercise`

## TDD verification from implementation

RED failure was observed when the focused test called `write_approved_paper_recommendations(..., broker_enrichment=...)` before the parameter existed:

```text
TypeError: write_approved_paper_recommendations() got an unexpected keyword argument 'broker_enrichment'
```

Focused verification:

```bash
cd /root/.hermes/wolfy
uvx --with pytest --with psycopg[binary] pytest \
  test_robinhood_broker_enrichment.py \
  test_eod_signals.py::test_write_approved_paper_recommendations_adds_robinhood_broker_enrichment_without_live_orders \
  test_eod_signals.py::test_log_approved_paper_recommendation_trades_creates_open_paper_rows_idempotently -q
```

Result: `3 passed`.

Full verification required `pyyaml` for unrelated config guardian tests:

```bash
cd /root/.hermes/wolfy
uvx --with pytest --with psycopg[binary] --with pyyaml pytest -q
```

Result: `129 passed`.

Do not encode `pyyaml missing` as an environment rule; the durable lesson is that Wolfy full-suite verification via `uvx` needs the same transient dependency set as the tests exercise.

## Next integration step

Once Robinhood MCP tools are callable in a fresh/reloaded Hermes session, add a fetcher that calls the read-only MCP tools for each approved candidate, builds payloads with `make_read_only_enrichment_payload`, merges them by ticker, then passes the mapping into `write_approved_paper_recommendations(..., broker_enrichment=...)`.

Maintain the invariant: Robinhood data can block/warn/enrich paper recommendations, but deterministic Wolfy signals still decide candidate creation.