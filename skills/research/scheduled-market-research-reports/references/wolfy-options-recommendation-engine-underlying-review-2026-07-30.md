# Wolfy options recommendation engine: underlying setup-review gate — 2026-07-30

Session learning for `scheduled-market-research-reports`.

## User decisions captured

The user approved proceeding with implementation defaults for the first recommendation strategy, while preserving strategy-approval and no-live-execution gates.

Current first implementation target:

- Strategy name: `liquid_rs_breakout_continuation`.
- Purpose: 1–2 week bullish defined-risk options ideas, evaluated from EOD data for next-session review/trigger.
- Trigger: close above the prior 5-trading-day high.
- Relative strength: ticker 20-trading-day return must exceed SPY 20-trading-day return.
- Volume confirmation: `vol_ratio >= 1.2`.
- Tightness/near-high: close within 5% of recent high before/at breakout.
- Stop/invalidation: below prior 5-day low.
- Time stop: max 10 trading days.
- Profit plan: take partial at 1.5R, trail remainder.
- Preferred option expression: 2–3 week slightly OTM call spread.
- Equity/ETF fallback: allowed only if labeled as fallback.
- Regime: soft Sentinel gate, not a deterministic hard block in v1.
- Gap chase: do not chase next-session open if >0.5 ATR above breakout trigger.
- Report limit: max 3 paper-eligible recommendations plus watchlist alternates.

## Important user correction: options liquidity is informational

The user explicitly corrected the earlier assumption that options liquidity should be a hard gate:

> “I don’t need liquidity to be a factor. I will evaluate myself when placing the trade.”

Implementation consequence:

- Do **not** block paper recommendations or Postgres paper logging only because option OI/volume/spread are thin or unknown.
- If option-chain data exists, surface OI/volume/spread as fields/warnings.
- Mark liquidity as `user_to_evaluate_manually` / `option_liquidity_hard_gate=false`.
- Keep other hard gates: deterministic setup, strategy approved by human after validation, stop/invalidation, max 3 open paper positions, Sentinel approval, Yang approval, Postgres-only paper logging, no live execution.

## Important user correction: evaluate setup accuracy, not user P/L

The user clarified that Wolfy will not know actual manual trade timing/fills:

> “For evaluating success, we should be looking at the underlying stock, and whether the technical setup panned out. Did it continue higher, and if so by how much… You won’t know when and at what price I put the trade on so evaluating the setup accuracy.”

Implementation consequence:

- Evaluate recommendation quality by underlying ticker movement from the EOD signal / next-session trigger framework, not the user’s actual option-spread P/L.
- Add a post-trade/post-recommendation review gate that records:
  - max favorable excursion over the intended horizon,
  - max adverse excursion,
  - whether the underlying hit 1.5R before invalidation,
  - whether it broke prior-5-day-low invalidation,
  - days to best move,
  - close after 5 trading days,
  - close after 10 trading days,
  - continuation magnitude,
  - classification: `successful_continuation`, `partial_success`, `failed_breakout`, `stopped_or_invalidated`, or `no_follow_through`,
  - concise rule-improvement note.
- This is an accountability/learning gate for the strategy and recommender, not an audit of the user’s personal execution.

## Agentic loop update pattern

When translating these decisions into implementation cards/tasks, dependency chain should include:

1. Seed `liquid_rs_breakout_continuation` as `research_only`.
2. Generate deterministic RS-breakout signals.
3. Apply broad-current universe + safety/data/tradability/manipulation gates.
4. Harden OOS validation gates: OOS Sharpe >= 0.75, OOS max drawdown < 15%, dynamic sufficient-trade count.
5. Run validation.
6. Add approved-gated recommendation writer.
7. Add Sentinel/Yang review integration.
8. Add Postgres-only paper-trade auto-logging gate.
9. Add visible ledger recommendation-engine status.
10. Add underlying setup-success post-review gate.

Do not interpret “I’m good with all recommendations” as approval to mark a strategy `approved`; it means accept the recommended implementation defaults. Strategy approval remains a later explicit human gate after validation evidence is shown.
