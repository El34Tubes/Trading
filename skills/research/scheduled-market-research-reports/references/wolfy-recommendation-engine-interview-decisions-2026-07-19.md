# Wolfy recommendation-engine interview decisions — 2026-07-19

Use this reference when Wolfy is being optimized from research/watch-only toward EOD paper-trade recommendations.

## User-selected operating decisions

- Git/code cleanup: commit and push **safe source/config/doc changes only**; do not blindly stage runtime logs, databases, caches, scratch files, generated reports, or unrelated profile snapshots.
- Jonah cadence: **pause Jonah temporarily** until recommendation-engine validation is done, to free token/implementation budget. Resume later at a slower cadence after validation or when source ingestion is needed.
- First recommendation universe: user said **include all**; interpret as broad/current universe while still enforcing liquidity, tradability, manipulation-risk, long-only, stop/risk, and review gates.
- Earnings/event uncertainty: allow recommendations if **no known event** appears; for known events, let Sentinel decide case-by-case.
- Paper risk: $5,000 paper account, **2% risk per trade**, max **3 open positions**, stops required.
- Reward/risk: allow **1.5R minimum** if setup quality/probability is strong.
- Instruments: **prefer options when available**, but only defined-risk structures; let Options/Sentinel choose the specific defined-risk structure. Equities/ETFs remain allowed.
- Paper logging: user approval is **not** needed for paper trades after system review. Auto-log only after **both Sentinel and Yang approve**.
- Postgres paper logging: paper trades must be logged to **Postgres `paper_trades` only**. Do not route live paper logging through legacy SQLite helpers; if a helper is SQLite-only, migrate/bridge it to Postgres before using it in the live path.
- Daily paper-trade limit: user clarified **limit to 3 open positions**; do not interpret the earlier "10/day" as permission to exceed 3 open paper positions. If more than 3 ideas appear, treat extras as shadow/watchlist/evaluation candidates unless slots are free.
- Notifications: daily summary only — new paper trades, exits, and performance; avoid per-trade spam unless user changes this.
- Holding period: let strategy decide dynamically.
- Win rate vs asymmetry: let strategy decide and report the tradeoff.
- Exits: use strategy-specific exit rules with ATR/time safety stops.
- Ranking overflow: blend validation, technical quality, liquidity, and risk score.
- Validation before candidate: require strategy to pass OOS before candidate status.
- Candidate promotion metric: OOS Sharpe **>= 0.75** with sufficient trades; let Wolfy choose sufficient OOS trade count by strategy frequency.
- Max validation drawdown: OOS max drawdown under **15%**.
- Strategy demotion/retirement: demote immediately after a risk-rule breach or 15% strategy drawdown.

## Interview-style decision workflow

When the user asks to resolve Wolfy blockers/config decisions, use interview-style clarification with selectable options, one decision at a time. Avoid dumping a long questionnaire. After each choice, record it and proceed to the next meaningful gate.

Recommended sequence:

1. Git/source-control handling.
2. Token/budget lever: Jonah pause/reduce/keep/raise cap.
3. Recommendation universe.
4. Earnings/event uncertainty.
5. Paper risk profile.
6. Minimum reward/risk.
7. Instrument rules.
8. Paper-trade logging approval flow.
9. Auto-log gate: Sentinel/Yang/deterministic.
10. Open-position / daily-limit conflict resolution.
11. Notification cadence.
12. Holding period.
13. Known-event strictness.
14. Validation strictness.
15. Candidate metric and drawdown tolerance.
16. OOS trade-count floor.
17. Win-rate vs reward-asymmetry preference.
18. Options structure preference.
19. Strategy demotion/retirement rule.
20. Exit model.
21. Ranking model when setups exceed available slots.

## Implementation direction chosen

Build toward `liquid_pullback_continuation` or equivalent narrow deterministic EOD strategy, but do not mark it `approved` without explicit user approval after validation. User approval to "go for recommendations" authorizes building the recommendation engine and auto-logging reviewed paper trades, not live trading or unvalidated strategy approval.

## Postgres-only paper-trade implementation gate

The paper ledger implementation task should require all of the following before inserting a row into Postgres `paper_trades`:

- originating strategy status is `approved`;
- deterministic signal/setup support exists and is referenced in recommendation notes/metadata;
- Sentinel approves;
- Yang approves or marks the setup technically valid;
- stop/invalidation, target/exit, entry trigger, instrument, and risk metadata are present;
- max 3 open paper positions is enforced;
- notes include `no_live_execution=true` or equivalent provenance;
- insertion is idempotent across cron reruns.

The expected plan/task wording is “Postgres paper-trade auto-logging gate,” not “human acceptance gate.” Paper logging is for learning/evaluation only and never authorizes broker/live execution or money movement.

## Pitfalls

- Do not treat "include all" as permission to ignore liquidity/tradability/manipulation gates.
- Do not treat "paper trades do not need approval" as permission to bypass strategy validation, Sentinel, Yang, max-3-position, stops, or no-live-execution boundaries.
- Do not write paper trades to SQLite or revive retired SQLite live paths; Postgres `paper_trades` is the required ledger.
- Do not keep Jonah at high cadence while implementation budget is blocked; pause/reduce research until validation is done.
- Do not ask all questions in prose with numbered options embedded in text; use selectable choices via the clarification UI when available.
