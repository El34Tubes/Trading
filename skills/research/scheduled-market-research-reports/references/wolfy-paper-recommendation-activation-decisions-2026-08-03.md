# Wolfy paper-recommendation activation decisions — 2026-08-03

Session class: options-focused EOD recommendation engine / paper-trade activation.

## Durable decisions

The user approved moving forward from a validated candidate strategy into paper-only recommendation generation.

- Approved strategy for paper recommendations/logging: `liquid_rs_breakout_close_confirm_1r`.
- Approval scope: paper recommendations and Postgres paper logging only; no live execution, no broker authority, no money movement.
- Future strategies: may auto-activate for paper recommendations if they pass the same setup-outcome-native validation gate and stay inside the paper-only/no-live boundary.
- Review gates: user explicitly chose to bypass Sentinel/Yang and all review gates for paper recommendations and paper logging.
- Recommendation cap: max 3 paper-eligible recommendations per day.
- Paper risk: 5% paper-account risk per trade; prior 1–2% default is too low for this paper-testing mode.
- Max open positions: no max-open cap for paper testing.
- Entry baseline: use EOD close as the paper-entry baseline.
- Instrument row: log equity fallback and, when option data exists, option-spread structure; options liquidity remains informational/user-evaluated, not a hard gate.
- Notifications: daily summary only.

## Implementation implications

1. The approved-gated writer should allow only approved deterministic strategies, starting with `liquid_rs_breakout_close_confirm_1r`.
2. The writer/logger must still be Postgres-only and must not create any live order/execution path.
3. Immediate paper logging may be triggered by a deterministic approved-strategy signal alone; do not require Sentinel/Yang for this paper-only workflow.
4. Strategy approval semantics changed for this user: a strategy that passes the current setup-outcome-native gate may become paper-active automatically, but this does **not** imply real-money/live approval.
5. Keep daily reporting concise and table-based: recommendations created, paper rows logged, open/closed setup outcomes, and any gate failures.

## Pitfall caught

Do not overwrite the user’s new paper-testing risk settings with older defaults from memory/skills. Older defaults were `$5k`, `2% risk/trade`, and `max 3 open positions`; the latest paper-testing decision is `5% risk/trade` and **no max-open cap**, while retaining max 3 paper recommendations per day.
