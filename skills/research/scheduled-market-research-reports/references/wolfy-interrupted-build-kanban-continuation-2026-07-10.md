# Wolfy interrupted build continuation / next-card dispatch pattern — 2026-07-10

Use when the user says a prior prompt was interrupted and asks to continue Wolfy build work.

Pattern:

1. Recover the previous session/request before acting.
   - Use session history to identify the interrupted user intent and the last assistant/tool state.
   - In this case the interrupted request was: "Let's do the next cards for build" after a progress audit showed the next target was tiered EOD data coverage/backfill and OOS validation.

2. Re-ground before creating cards.
   - Verify available Hermes profiles before assigning work. Current working profiles were `default`, `clerky`, `mike`, and `yang`.
   - Inspect Kanban board state/stats to avoid duplicate flat cards.
   - Check current Wolfy ledger facts: cron health, prices/features freshness, tiered coverage gaps, strategy statuses, setups/paper-trade counts, and any budget/usage gate state.

3. Write a durable project-plan artifact under `/root/.hermes/wolfy/` before card fan-out.
   - The plan should include current measured state, dependency graph, and autonomy/blocking rules.
   - This gives workers a stable source of truth and avoids relying only on a chat transcript.

4. Create dependency-linked Kanban cards with idempotency keys.
   - Parent lane A: runtime/control-plane blocker if present, e.g. budget-gate/runtime issue.
   - Parent lane B: main data/build lane, e.g. bounded tiered EOD backfill.
   - Child: post-backfill deterministic recompute/readiness report.
   - Child: strategy OOS validation only after coverage gate passes.
   - Final child: integration smoke/report-context handoff, depending on both runtime and validation lanes.

5. Preserve Wolfy safety language in every card.
   - EOD-only, deterministic gates, no auto-execution, no setups/paper trades without an approved strategy.
   - Routine code/test/schema-compatible implementation may proceed autonomously.
   - Block only for destructive DB/package changes, paid credentials/API keys, broker/live-trading authority, legal/data-access blockers, or human strategy approval.

6. Dispatch and verify.
   - Run `hermes kanban dispatch --dry-run --max N --json` first to confirm only independent parents spawn.
   - Then run `hermes kanban dispatch --max N --json`.
   - Verify with `hermes kanban list`, `hermes kanban stats`, and `hermes kanban runs <task_id>` for spawned parents.

Concrete graph used:

- `t_41da1e1d` — Mike — repair optimizer budget-gate runtime blocker — running.
- `t_9d1fca3a` — default — execute/repair bounded tiered EOD backfill coverage — running.
- `t_cac43e42` — default — post-backfill deterministic recompute and coverage report — depends on backfill.
- `t_9fdfd748` — default — rerun strategy OOS validation after coverage gate — depends on recompute.
- `t_1452a9a1` — Clerky — integration smoke and report-context handoff — depends on runtime blocker and validation.

Do not encode transient environment errors as durable rules. If a runtime dependency check fails, card the repair/proof as a bounded worker task and require real command output in the handoff.