# Wolfy recommendation-engine interview + options strategy decisions — 2026-07-29

Use this as session-specific detail for future Wolfy recommendation-engine planning/implementation.

## Interview workflow that worked

When the user asks to resolve optimization/recommendation blockers, use interview-style selectable questions rather than a single broad prompt. Ask one decision at a time with concise options, record answers, and continue until the implementation boundary is clear. The user explicitly prefers this for Wolfy optimization/configuration decisions.

## Autonomy decisions captured

- Commit/push safe source/config/doc changes only; do not blindly commit runtime/generated state.
- Pause Jonah temporarily until recommendation-engine validation is done to free budget for implementation.
- Broad/current universe is allowed for the first recommendation engine, but deterministic gates still apply.
- Earnings/event unknown should not automatically block recommendations; if no known event appears, recommendations may proceed, with Sentinel deciding known event edge cases.
- Paper settings: $5k paper account, 2% risk/trade, max 3 open positions, stops required.
- Paper trades do not need case-by-case user approval; auto-log only after both Sentinel and Yang approve.
- Daily notification only: new paper trades, exits, and performance.
- Paper trading must log to Postgres `paper_trades`; no live trading, broker path, or SQLite fallback.

## Validation / promotion preferences

- Require OOS pass before candidate status.
- OOS Sharpe threshold: >= 0.75.
- OOS max drawdown: < 15%.
- Sufficient OOS trade count should be chosen by Wolfy according to strategy frequency.
- Let each strategy report win-rate vs reward-asymmetry tradeoff rather than hard-coding a global preference.
- Strategy exits should be strategy-specific with ATR/time safety stops.
- Demote immediately on risk-rule breach or 15% strategy drawdown during paper testing.

## First technical strategy to implement

Strategy name: `liquid_rs_breakout_continuation`.

Purpose: 1–2 week defined-risk options-focused breakout strategy.

Rules selected by interview:

- Setup type: relative-strength breakout / tight consolidation expansion.
- Breakout trigger: 5-day high breakout.
- Relative strength: must outperform SPY over 20 trading days.
- Volume: require `vol_ratio >= 1.2` on breakout.
- Consolidation/tightness: close must stay within 5% of recent high before breakout.
- Stop/invalidation: stop below prior 5-day low.
- Time stop: 10 trading days max hold.
- Profit rule: take partial at 1.5R and trail remainder.
- Options expiration: 2–3 weeks out.
- Preferred bullish structure: slightly OTM call spread.
- Options liquidity: user evaluates manually when placing the trade; do not make OI/volume/spread a hard paper-recommendation gate. Surface liquidity info/warnings if available.

## Implementation implications

- Deterministic signal row first; LLM only explains/ranks/reviews.
- Strategy may become `candidate` only after validation passes; only the user can explicitly mark it `approved`.
- Approved-gated setup -> Sentinel review -> Yang technical review -> Postgres recommendation -> Postgres `paper_trades` auto-log.
- `paper_trades.notes` should include source ids (`strategy_id`, `signal_id`, `setup_id`, review ids), `no_live_execution=true`, and `option_liquidity_user_evaluated=true` when relevant.
- Options liquidity must not block paper logging by itself; missing stop, missing deterministic setup, missing Sentinel/Yang approval, max-position breach, non-approved strategy, or live/broker path must block.
