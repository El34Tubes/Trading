# Wolfy optimizer plan-only closure under a token-cap block (2026-08-14)

Use this pattern when the deterministic budget gate blocks a scheduled optimizer before implementation.

## Preconditions and hard stop

1. Run the budget gate first, preferably with `--no-record` when a later ledger transaction will write the run metrics.
2. A nonzero result such as `BUDGET=block token_cap_exceeded ...` is a hard implementation stop.
3. After the block, permit only deterministic review and durable state updates: guardian/config/cron health, task/run/KPI ledger closure, and a narrowly staged optimization note. Do not edit code, config, cron, or migrations.

## Durable closure sequence

1. Verify the config guardian with the production home pinned:
   `python3 wolfy/guardian/config_guardian.py --home /root/.hermes --skip-cli`.
2. Confirm no probation marker, parse `config.yaml` and `cron/jobs.json`, check the production-profile cron list and gateway, run the visible-progress ledger, and run the Postgres requirements guard.
3. Re-verify the prior optimizer task's stored Definition of Done and commit hash before creating today's plan-only task.
4. Create/ensure a date-fingerprinted `agent_task`, claim it, and start a linked `agent_run`. Keep the implementation candidate queued rather than claiming it.
5. Add one concise top-of-ledger entry to `wolfy/optimization_todo.md`: budget result, guardian/cron state, task/run IDs, lesson, and next action.
6. In a dirty live-state repository, stage only that ledger path, run `git diff --cached --check`, scan the staged diff for secrets, and commit only the note. Never use `git add .`.
7. Insert one `loop_metrics` row per required KPI for the run. Verify the count before marking either ledger row complete. When a metric is not freshly recomputed during a plan-only run, explicitly label a carry-forward value in `notes` rather than presenting it as a new measurement.
8. Store `definition_of_done`, `verification_result`, `verified_at`, and the real commit hash on `agent_tasks`; then complete the task and finish the run with the actual metric-row count in `records_created`.
9. Final verification should prove: task completed, run completed, expected metrics count, zero stale started runs, guardian exit 0, cron-list exit 0, and the commit contains only the intended ledger file.

## KPI completeness

Cover every configured class, not only notable report fields:

- `orchestration/cost`: calls, tokens, headroom, budget skips, rollbacks, gateway, max turns, parallel cap.
- `data_health`: freshness coverage, maximum lag, depth readiness.
- `migration`: live legacy references, parity failures, Postgres paper ledger, Postgres scorecard.
- `loop_health`: trailing success rate, regressions, recurring failures, human approvals pending.
- `strategy`: candidate, approved, OOS-complete counts.
- `repo_health`: tracked files, tracked size, duplicate script groups.

The user-facing report should remain short: CHANGED, VERIFIED, notable KPI/STATE, Tier-B HUMAN ASK only when one exists, and NEXT ACTION. A budget block is reportable because it changes durable optimizer state even though no implementation occurred.

## Pitfalls

- Do not call the budget gate in recording mode and then accidentally double-count the skip during the explicit KPI transaction.
- Do not invent a current metric from an absent table or guessed schema. Inspect the live schema or use a clearly labeled latest-measured carry-forward.
- Do not leave the plan-only task or run in `started`/`in_progress` after committing the ledger note.
- Do not turn a dirty worktree into a reason to skip durable state; isolate the one intended ledger file in the index.
