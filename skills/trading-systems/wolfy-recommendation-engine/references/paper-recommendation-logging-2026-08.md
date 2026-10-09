# Paper recommendation logging notes — 2026-08

This reference captures session-specific implementation details for Wolfy's approved paper recommendation writer and Postgres paper-trade logger.

## Implemented behaviors

- `write_approved_paper_recommendations(conn, signal_dt=..., tickers=None, max_recommendations=3, dry_run=False)` writes `recommendations.status='paper_candidate'`.
- `log_approved_paper_recommendation_trades(conn, signal_dt=None, tickers=None, max_trades=3, dry_run=False)` writes `paper_trades.status='open'` and marks recommendations `paper_logged`.
- Both paths are paper-only and produce no broker actions.
- Idempotency:
  - recommendation writer treats both `paper_candidate` and `paper_logged` as existing;
  - paper logger skips if a `paper_trades.recommendation_id` row already exists.

## Eligibility gate

Do not use `strategies.status='approved'` alone. Require explicit paper approval metadata:

```text
status = approved
metadata.approval_scope = paper_only_no_live_execution
metadata.paper_recommendation_approval = true
```

This came from a live-state pitfall: a generic `trend_volume_vol_regime` row had been left `approved` by old tests/state even though the user only approved `liquid_rs_breakout_close_confirm_1r` for the paper flow.

## Live smoke result from implementation session

The live paper-only smoke created one open paper trade:

```text
ticker: LTC
strategy: liquid_rs_breakout_close_confirm_1r
entry_date: 2026-07-14
entry_price: 40.03
quantity: 833.3333333333334
stop_price: 39.73
target_price: 40.33
status: open
no_live_execution: true
broker_order_submitted: false
```

Two stray paper candidates (`JPM`, `XLF`) from the generic strategy were deleted because they were not from the explicitly paper-approved strategy and had invalid stop risk. The generic strategy was reset to `research_only`.

## Test commands that passed

```bash
cd /root/.hermes/wolfy
python3 -m pytest test_eod_signals.py::test_log_approved_paper_recommendation_trades_creates_open_paper_rows_idempotently -q
python3 -m pytest test_eod_signals.py -q
python3 -m pytest -q
```

Observed results:

```text
focused logger test: 1 passed
test_eod_signals.py: 11 passed
full suite: 125 passed
```

## Git and task-board result

```text
commit: 3d409e2b2a11dac7fb6ac74eb4e59b2c1cc523b4
message: wolfy(rec): log approved paper trades
task: 3584 completed
```

The `agent_tasks` schema did not have `result_payload`; update task board rows through existing columns such as `summary`, `payload`, `verification_result`, `commit_hash`, and `metadata`.
