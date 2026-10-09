# Wolfy budget-blocked plan-only run + staged-diff safety (2026-07-11)

## Trigger

Use this reference for Wolfy daily self-optimization runs when the proactive budget gate blocks implementation and the repo is already dirty/staged from other automation.

## Observed pattern

- `python3 wolfy/guardian/budget_gate.py` returned `BUDGET=block token_cap_exceeded tokens_today=309142 cap=200000`.
- The run correctly switched to PLAN-ONLY: deterministic orientation/review, guardian health, Postgres task/run + `loop_metrics`, and ledger update only.
- `python3 wolfy/guardian/config_guardian.py` returned `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;hermes_cron_list_ok;no_probation`.
- `hermes cron list` succeeded.
- A narrow ledger commit was intended, but the first commit accidentally included pre-existing staged deletions (`wolfy/init_wolfy_db.py`, `wolfy/queue_knowledge_source_files.py`, `wolfy/sync_sqlite_to_postgres.py`) because the dirty repository already had staged changes.

## Recovery pattern

If a commit accidentally includes unrelated staged changes:

```bash
git reset --soft HEAD~1
git restore --staged .
git add wolfy/optimization_todo.md
git commit -m "wolfy(opt): record budget-blocked plan-only run — DoD met (task <id>)"
git show --stat --oneline --name-status HEAD | cat
```

This preserves working-tree edits, clears the polluted index, and recommits only the intended verified file.

## Commit safety rule for future Wolfy optimizer runs

Before any local commit in the Wolfy/Hermes dirty ops repo:

```bash
git diff --cached --name-status | cat
```

If anything outside the intended narrow file set is staged, run:

```bash
git restore --staged .
git add <intended files only>
git diff --cached --name-status | cat
```

Only then commit. This is especially important in cron/optimizer contexts because other profile/curator/autorepair jobs may leave staged or dirty files unrelated to the current task.

## State/result from this run

- Postgres task: `3544`, completed with DoD text.
- Postgres run: `295717`, completed as plan-only.
- Metrics recorded: `jobs_skipped_by_budget=1`, `gateway_healthy=1`, `config_rollbacks=0`, `parallel_jobs_cap=1`, `max_turns=90`, `human_approval_pending=0`, trailing `iteration_success_rate`.
- Final corrected commit: `7cf352d` with only `wolfy/optimization_todo.md`.

## Reporting shape

Final report stayed concise:

- `CHANGED`: plan-only budget block + durable state update.
- `VERIFIED`: budget gate block, guardian ok, cron list ok, commit hash.
- `KPI/STATE`: notable metrics only.
- `BLOCKED/HUMAN ASK`: none unless Tier B exists.
- `NEXT ACTION`: wait for budget recovery, then one bounded Tier S control-plane slice.
