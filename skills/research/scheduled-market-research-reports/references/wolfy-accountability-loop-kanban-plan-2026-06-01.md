# Wolfy Accountability Loop Kanban Plan — 2026-06-01

Session lesson: when the user asks to move Wolfy implementation priorities forward and "Kanban them" with no further prompting, treat that as authority to create/advance Kanban work and kick the dispatcher, not merely describe a plan.

## Verified pattern used

1. Inspect current Wolfy state before planning:
   - `wolfy_status.py` for DB/storage/table counts.
   - `hermes --profile default cron list --all` for active jobs.
   - SQLite counts for `recommendations`, `paper_trades`, `recommendation_outcomes`, `reports`, `alpha_leads`, etc.
2. Identify the actual implementation bottleneck. In this case the desk was producing reports/leads, but had zero recommendations/paper trades/outcomes.
3. Review existing Kanban board before creating duplicates:
   - `hermes profile list`
   - `hermes kanban boards list`
   - `hermes kanban list --json --sort priority-desc`
4. If a blocked card is actually implementation-complete but waiting for review, verify it with real commands before completing it. In this case:
   - `python /root/.hermes/wolfy/check_postgres_requirements.py`
   - focused pytest suite returned `18 passed in 0.32s`
   - then card `t_736821fa` was commented and completed.
5. Create dependency-linked Kanban cards for the missing accountability loop:
   - scanner freshness gate
   - lead-to-recommendation promotion gate
   - report-flow integration
   - Sentinel structured review persistence/status updater
   - paper portfolio engine/outcome grader
   - end-to-end smoke test / cron handoff
6. Save an implementation plan into the project (`/root/.hermes/wolfy/IMPLEMENTATION_PLAN_ACCOUNTABILITY_LOOP.md`) so future workers have a durable handoff.
7. Add comments to active cards telling workers to proceed autonomously and only block for destructive DB/package changes, paid APIs, broker/live-trading authority, or legal/data-access blockers.
8. Run `hermes kanban dispatch` to start work immediately.

## Dependency shape

```text
P1 scanner freshness
  -> P2 lead promotion
    -> P3 Wolfy report integration

Recommendation logger [verified done]
  -> P4 Sentinel persistence
    -> P5 paper-trade/outcome engine
      -> weekly scorecard

P6 end-to-end smoke test depends on P3 + P4 + P5
```

## Pitfalls

- Do not create duplicate cards before checking the existing board; previous Wolfy cards may already represent part of the plan.
- Do not mark a review-required card done without rerunning its verification commands.
- Do not let the plan remain prose-only. Save it, create cards, link dependencies, and dispatch.
- Do not ask the user for routine code/test/schema-compatible changes after they explicitly authorized autonomous implementation.
- Do not give broker/live-trading authority or place real trades; the autonomy is for implementation and paper-trading infrastructure only.
