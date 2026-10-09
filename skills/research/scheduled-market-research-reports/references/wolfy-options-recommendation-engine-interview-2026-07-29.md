# Wolfy Options-Focused Recommendation Engine Interview — 2026-07-29

Use this reference when continuing the user's Wolfy recommendation-engine build, especially when planning or implementing technical strategies intended to produce paper-trade recommendations.

## User decisions captured

| Area | User decision |
| --- | --- |
| Build autonomy | Wolfy may build without user intervention for a while; ask only for true human gates. |
| Git cleanup | Commit and push safe source/config/doc changes only; do not blindly commit runtime logs, DBs, caches, scratch artifacts, or generated reports. |
| Jonah cadence | Pause Jonah temporarily until recommendation-engine validation is done, to preserve budget for implementation. |
| First recommendation universe | Include the broad/current universe, but enforce liquidity, history, data-quality, Robinhood/practical tradability, and manipulation/government-interference gates. Do not exclude by tier alone. |
| Earnings unknown | Allow recommendations if no known event appears; for known events, let Sentinel decide case-by-case. |
| Paper risk | $5,000 paper account; 2% risk/trade; max 3 open positions; stops required. |
| Instruments | Prefer options when available, but only defined-risk structures. Let Options/Sentinel choose the specific defined-risk structure. |
| Reward/risk | Allow 1.5R minimum if setup probability/quality is strong. |
| Paper logging | No user approval needed for paper trades; auto-log only after both Sentinel and Yang approve. Log to Postgres `paper_trades` only; no SQLite fallback; no broker/live execution. |
| Notifications | Daily summary only: new paper trades, exits, and performance. |
| Holding period | Let strategy decide dynamically; for the first options-focused strategy, use 10 trading days max hold. |
| Validation | Require OOS pass before candidate status; OOS Sharpe >= 0.75, max OOS drawdown < 15%, sufficient trades chosen by strategy frequency. |
| Demotion | Demote immediately after risk-rule breach or 15% strategy drawdown. |
| Exits | Strategy-specific exit rules with ATR/time safety stops. |
| Ranking | Blend validation strength, technical quality, liquidity, and risk score when more setups pass than slots are available. |

## First implementable technical strategy

Name: `liquid_rs_breakout_continuation`

Purpose: 1–2 week defined-risk options setup on liquid relative-strength leaders breaking out of short consolidation.

Prefer this over a slow pullback-to-20MA for the first options engine because options need cleaner timing, nearer expected movement, and less premium bleed.

### Deterministic v1 rules

A signal fires when all are true:

1. **Breakout:** close today breaks above the prior 5 trading-day high.
2. **Relative strength:** ticker 20-trading-day return outperforms SPY 20-trading-day return.
3. **Volume:** `vol_ratio >= 1.2` on breakout.
4. **Consolidation/tightness:** before breakout, close stays within 5% of the recent high.
5. **Trend:** close > fast MA > slow MA, using stored features.
6. **Stop/invalidation:** below prior 5-day low.
7. **Time stop:** 10 trading days max hold.
8. **Profit management:** take partial at 1.5R and trail remainder.
9. **Risk and instrument gates:** defined-risk options preferred when options liquidity supports it; otherwise equity/ETF fallback only if allowed by implementation gate. Max 3 open paper positions.
10. **Reviews:** Sentinel and Yang must both approve before Postgres paper-trade auto-log.

### Planned row flow

```text
EOD prices/features
→ deterministic signal: liquid_rs_breakout_continuation
→ OOS validation
→ candidate only if OOS passes
→ explicit human approval before strategy status='approved'
→ approved-gated setup row
→ Sentinel risk review
→ Yang technical entry/exit review
→ Postgres recommendation row
→ Postgres paper_trades auto-log
→ daily paper performance summary
```

## Implementation notes

- The user has approved building the recommendation engine, not auto-approving any strategy.
- Human approval is still required to change a strategy row to `approved` after validation.
- Paper trades may be logged automatically only after both Sentinel and Yang approve and only into Postgres `paper_trades`.
- Keep all live Wolfy market/recommendation paths Postgres-only. Legacy SQLite helpers such as older recommendation/Yang modules must be migrated or bypassed for live paper logging.
- If current code still references a prior plan name like `liquid_pullback_continuation`, update the plan/tasks to the options-focused `liquid_rs_breakout_continuation` unless the user explicitly reverts.
