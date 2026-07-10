# Wolfy daily optimization short completion reports — 2026-07-01

Session signal: the user asked for short reports after each day's optimizations complete, delivered when done if possible. This followed an earlier correction that 429 reporting should be event + time only, not raw error logs.

## Durable pattern

When operating the Wolfy daily optimization planner or related self-optimizing cron jobs:

1. Ensure the cron job's final response is the user-facing completion report when delivery is available (`deliver: origin`/Discord/etc.).
2. Keep the report compact; do not paste long verification logs.
3. Preferred shape:
   - `CHANGED` — 1-3 bullets, only actual durable changes.
   - `VERIFIED` — command/status summary and commit hash if one was produced.
   - `KPI/STATE` — only notable deltas or go/no-go state.
   - `BLOCKED/HUMAN ASK` — only Tier B items: installs/upgrades, new credentials/secrets, or strategy approval.
   - `NEXT ACTION` — one concrete next step.
4. For 429/usage-limit events: report only `usage-limit/429 event at <time>` plus the operational decision (for example LLM jobs remain paused/gated; script-only jobs continue). Do not include raw matching lines, stack traces, dashboards, or repeated log excerpts unless the user asks for details.

## Concrete update applied in-session

The optimizer cron prompt for job `92f31b95fccc` was patched so Phase 7 became `KPIs + SHORT COMPLETION REPORT`, and `/root/.hermes/wolfy/optimization_todo.md` gained an operating-constraints bullet saying daily optimization runs should send a short completion report when done. Future prompt edits should preserve this preference.
