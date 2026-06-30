# Sector Cross-Sectional Momentum — Strict Revalidation Package

Generated: 2026-06-26 UTC

Governance: EOD-only, deterministic signals only, no auto-execution, no broker authority, human approval required for any strategy to become actionable.

## Decision

NOT ELIGIBLE FOR HUMAN APPROVAL YET.

The strategy was challenged under stricter technical-trading assumptions and failed. It has been demoted back to `research_only` in Postgres. It must not create paper setups or capital recommendations.

## Strict revalidation run

| Field | Value |
| --- | --- |
| Strategy | sector_cross_sectional_momentum |
| Backtest ID | 62 |
| Window | 2024-09-03 → 2026-06-25 |
| OOS split | 126 exit dates |
| Slippage | 25 bps |
| Commission | $0 |
| Minimum OOS Sharpe gate | 1.5 |
| IS Sharpe | -1.1053 |
| OOS Sharpe | -0.5813 |
| OOS CAGR | -0.2633 |
| Max drawdown | -0.9995 |
| Turnover | 9.4146 |
| Trades / OOS trades | 4246 / 1197 |
| Survived strict OOS | false |
| Postgres status after challenge | research_only |

## Technical interpretation

FACT: The earlier permissive run showed positive OOS statistics, but the stricter run collapsed under higher friction and a longer OOS split.

FACT: Turnover remained very high, which is a bad fit for a $5,000 account, max 3 positions, stop discipline, and PDT avoidance.

FACT: The max drawdown is unacceptable. This cannot be paper-trade-ready without position limits, ranking throttles, stop logic, and stronger regime filters.

JUDGMENT: The raw idea may still be useful as a research signal or ranking feature, but it is not viable as an approved strategy in current form.

## Required modifications before reconsideration

1. Convert it from broad cross-sectional churn into a limited top-N technical setup:
   - max 1-3 concurrent names;
   - only top-ranked liquid U.S. names/ETFs;
   - no low-liquidity, no stale scanner data;
   - skip extended/gap-reversal names.
2. Add stop/invalidation modeling:
   - ATR-based stop;
   - max loss per position;
   - no signal without stop distance and target logic.
3. Add market-regime filter:
   - risk-on only, or sector leadership confirmed by SPY/QQQ/sector ETF trend;
   - avoid signals during broad-market breakdown/chop.
4. Add event/liquidity exclusions:
   - earnings window guard;
   - spread/ADV guard;
   - exclude suspicious/manipulation-prone names.
5. Re-run walk-forward with conservative costs:
   - at least 25 bps slippage;
   - 126+ OOS days;
   - max drawdown gate;
   - turnover gate suitable for small-account swing trading.

## Approval package status

No approval requested. No setup creation. No paper trade. This is a failed candidate challenge and a research-only handoff for redesign.
