# Wolfy approved-gated paper recommendation writer — 2026-08-06

## Class-level lesson

When Wolfy moves from validated/candidate strategies to paper recommendations, build a deterministic writer that emits Postgres `recommendations` rows from approved strategy signals only. Keep paper-trade ledger insertion as a separate step unless the user explicitly asks to combine them.

## Implemented pattern

Function shape added in the session:

```python
write_approved_paper_recommendations(
    conn,
    *,
    signal_dt: date,
    tickers: Sequence[str] | None = None,
    max_recommendations: int = 3,
    risk_fraction: Decimal = Decimal("0.05"),
    dry_run: bool = False,
) -> dict
```

Writer behavior:

- Reads deterministic rows from `signals` joined to `strategies`.
- Requires `strategies.status='approved'` and long/buy direction.
- Caps selected rows at `max_recommendations` (current user setting: 3/day).
- Writes Postgres `recommendations.status='paper_candidate'`.
- Uses `recommendation_type='equity_plus_option_spread_when_data_exists'`.
- Uses EOD close as paper accounting baseline.
- Includes 5% paper-risk guidance in `position_size_suggestion`.
- Stores `notes` metadata: `paper_only`, `no_live_execution`, `review_gate_required=false`, `sentinel_yang_required=false`, `paper_entry_baseline='eod_close'`, `source_signal`, `option_spread`, and `equity_fallback=true`.
- Does **not** insert into `paper_trades`; keep that for the Postgres paper-trade auto-logging gate.
- Supports `dry_run=True` for live smoke: ranked rows can be checked with zero created recommendations/paper trades.

## TDD and verification pattern

1. Write a failing test that imports the wished-for writer and verifies:
   - approved strategy signals produce rows;
   - research-only/candidate strategy signals are counted as blocked;
   - daily cap is enforced;
   - rows use `paper_candidate`, EOD close baseline, 5% risk text, and advisory option spread metadata;
   - `paper_trades` remain unchanged.
2. Watch the import/test fail before implementing.
3. Implement minimally.
4. Run the focused test, then full suite.
5. Run a live dry-run against the latest approved-strategy signal date and report before/after counts for `recommendations.status='paper_candidate'` and `paper_trades`.
6. Mark the relevant `agent_tasks` row completed only after tests, dry-run, narrow commit, and push.

## Live-DB fixture pitfall

Wolfy tests often use the production Postgres database. Use synthetic `ZZ...` tickers and far-future dates such as `2099-*`, and cleanup all tables touched by the flow (`recommendations`, `setups`, `signals`, `features`, `prices`, `earnings_calendar`, `universe_symbols`).

Do **not** let tests reset real strategy governance statuses. Seed/default-strategy tests should tolerate existing real statuses such as `candidate`/`approved`, or insert isolated unit strategies. If using `SPY` as a benchmark fixture, cleanup only future-date fixture rows and never delete real SPY history.

## Session verification snapshot

- Focused writer test passed after RED/GREEN cycle.
- Full Wolfy suite passed: `124 passed`.
- Live dry-run on the latest approved strategy signal date ranked 3 rows and created 0 rows.
- `paper_candidates` stayed `0 -> 0` and `paper_trades` stayed `0 -> 0` during dry-run.
- Narrow commit pushed: `8101c2a42d253268e2e6fa036c2aaa8610f9032e` (`wolfy(rec): write approved paper recommendations`).
