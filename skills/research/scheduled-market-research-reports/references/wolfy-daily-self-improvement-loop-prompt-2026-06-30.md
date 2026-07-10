# Wolfy daily self-improvement loop prompt update — 2026-06-30

## Context
The user provided a long replacement prompt for the `Wolfy daily optimization planner and implementer` cron job (`92f31b95fccc`) and approved an optimized, more compact version. The job is the daily 02:15 ET self-improvement loop for Wolfy.

## Durable pattern
When updating this class of Wolfy cron prompt, preserve the **loop mechanics** and **safety constitution**, but trim repeated language so the recurring run spends tokens on real state and implementation rather than re-reading redundant policy.

Recommended prompt structure:

1. Runtime and source-of-truth facts:
   - workdir `/root/.hermes`
   - Postgres DSN `dbname=wolfy user=root host=/var/run/postgresql`
   - Postgres-only live source of truth
   - durable state in `agent_tasks`, `agent_runs`, `loop_metrics`, and `optimization_todo.md`
2. Mission: review previous iteration, plan from deterministic state, execute ≤1–2 bounded Tier A tasks, verify against DoD, commit only verified work, record KPIs, leave one lesson.
3. Constitution/hard stops:
   - EOD-only
   - no auto-execution or broker authority
   - human-only strategy approval
   - deterministic signal path
   - no lazy installs
   - `check_postgres_requirements.py` before schema work
   - no destructive DB/package/config/schedule changes without human approval
4. Priority order:
   - EOD ingest/backfill reliability
   - visible progress ledger accuracy
   - Postgres-only migration / SQLite retirement
   - deterministic strategy validation after coverage
   - paper-trade accountability after approved-strategy gate
5. Tier A vs Tier B autonomy rules.
6. Machine-checkable Definition of Done requirement.
7. Phase order:
   - Orient
   - Review previous iteration
   - Plan
   - Conflict/gate check
   - Execute
   - Verify + commit
   - Reflect
   - KPI/report
8. Initial backlog, worked in order unless a higher-priority health issue is broken.

## Specific guardrail added
Add this planning guard to prevent overthinking the first iteration:

> If WS-1 is not complete, WS-1 is the default next task unless Priority 1 health is broken.

## Updated backlog shape from user
The revised backlog order is:

- WS-1: `agent_tasks` DoD/verification columns + `loop_metrics` table.
- WS-2: `task-approve` subcommand.
- WS-3: wire KPI emission into the loop.
- WS-4: dependency manifest + CI + SQLite guard test; install step remains Tier B.
- WS-5: adopt `wolfy_db` everywhere / retire SQLite, sliced 1–2 modules per run.
- WS-6: fix `scripts/` vs `wolfy/` wrapper-vs-implementation inversion, sliced.
- WS-7: broad-except audit, sliced.
- WS-8: repo hygiene / untrack runtime-vendored trees, Tier B recommendation only.
- WS-9: token/usage economy for LLM cron layer, Tier B recommendation only.
- WS-10: consolidate Kanban + `agent_tasks` + `optimization_todo.md`, Tier B direction first.

## Verification/commit pattern used
After updating the cron job, verify with:

```bash
hermes --profile default cron list --all | sed -n '/92f31b95fccc/,/886554b9a87e/p'
git -C /root/.hermes diff --stat -- cron/jobs.json
git -C /root/.hermes add cron/jobs.json
git -C /root/.hermes commit -m "wolfy(cron): refresh daily optimization backlog prompt"
```

Only commit `cron/jobs.json` for prompt changes. Leave unrelated curator/skill working-tree changes untouched unless they are the actual task.

## Pitfalls
- Do not let the optimizer edit other cron schedules/config as part of the daily loop; schedule/config changes are Tier B recommendations unless the user explicitly asks in the current session.
- Do not let the optimizer install dependencies; dependency recommendations must include exact package/version and wait for approval.
- Do not make the loop delete/untrack `profiles/`, `skills/`, `bin/tirith`, or retired SQLite paths; those are Tier B/human approval steps.
- Keep `hermes-agent` untouched if protected; put Wolfy-specific cron/self-improvement lessons under this market-research umbrella skill instead.
