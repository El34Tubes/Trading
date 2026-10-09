# Wolfy budget-gated plan-only optimizer run — 2026-07-10

## Trigger

Daily Wolfy optimizer started under the self-optimizing loop prompt. The deterministic budget gate returned:

```text
BUDGET=block token_cap_exceeded tokens_today=265417 cap=200000
```

Per the control-plane rules, this forces PLAN-ONLY mode: deterministic orientation/review/metrics are allowed, but no implementation, no config/cron changes, no LLM-job enablement changes, and no commit.

## Safe run shape

1. Run deterministic orientation first: ET time, `git status --porcelain`, `hermes cron list`, running processes, guardian manifest/probation, visible ledger, open tasks.
2. If `wolfy/guardian/budget_gate.py` blocks, stop before code/config edits.
3. Verify guardian state without modifying it:
   - `hermes cron list` succeeds.
   - `wolfy/guardian/manifest.json` points at a current known-good snapshot.
   - `wolfy/guardian/probation.json` absent or explicitly handled.
4. Persist the run as **blocked/plan-only** in Postgres when implementation was skipped due to budget, instead of pretending a Tier S task completed.
5. Insert `loop_metrics` rows that make the skipped work visible:
   - `jobs_skipped_by_budget=1`
   - `usage_headroom_pct=0` (or gate-reported value)
   - `tokens_today=<observed>`
   - `gateway_healthy=1` if cron list succeeded
   - `regressions_introduced=0` when no edits were made
6. Final report stays short: changed state, verified commands/status, KPI/state, human asks, next action.

## Important nuance

A gate script existing is not sufficient proof OWS-1 is complete. For every LLM cron job, especially Jonah, verify the cron-facing wrapper emits a final JSON line like:

```json
{"wakeAgent": false, "reason": "skipped: budget"}
```

when the budget gate blocks. Otherwise Hermes may still wake the agent and spend tokens after a script prints `skipped: budget`.

## Session outcome

- No code/config changes.
- No commit.
- `agent_runs.id=291669` recorded as blocked/plan-only.
- Metrics inserted for budget skip, headroom, tokens, guardian/cron health, max turns, parallel cap, and regressions.
