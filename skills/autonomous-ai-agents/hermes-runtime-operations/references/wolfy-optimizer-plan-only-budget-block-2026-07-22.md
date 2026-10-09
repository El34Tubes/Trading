# Wolfy optimizer plan-only budget block — 2026-07-22

## Trigger

Use this when the daily Wolfy optimizer starts under the self-optimizing loop and `wolfy/guardian/budget_gate.py` blocks implementation because the daily token cap is already exceeded. The correct behavior is PLAN-ONLY: review/state/KPI persistence only, with no code/config/cron changes.

## Concrete run outcome

- Time: 2026-07-22 02:16 ET / 06:16 UTC.
- Budget gate: `python3 wolfy/guardian/budget_gate.py --no-record` returned `BUDGET=block token_cap_exceeded tokens_today=291140 cap=200000` with exit `1`.
- Guardian: `python3 wolfy/guardian/config_guardian.py` returned `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;hermes_cron_list_ok;no_probation` with exit `0`.
- `hermes cron list` succeeded and optimizer job `92f31b95fccc` remained active.
- Persisted Postgres task `3596`, run `338871`, 24 `loop_metrics` rows, and a ledger entry in `wolfy/optimization_todo.md`.
- Local commit: `45aeabd` (`wolfy(opt): record budget-blocked optimizer run — DoD met (task 3596)`).

## Useful pattern: commit only the intended ledger hunk in a dirty repo

This repo often has unrelated dirty files from other profiles/jobs. For plan-only ledger commits, do not `git add wolfy/optimization_todo.md` blindly if the file already contains unstaged prior entries. Instead stage a minimal patch for the current run only:

```bash
# write the intended tiny hunk to /tmp/wolfy_<date>_ledger.patch
git apply --cached --recount /tmp/wolfy_<date>_ledger.patch
git diff --cached -- wolfy/optimization_todo.md
git commit -m 'wolfy(opt): record budget-blocked optimizer run — DoD met (task <id>)'
```

After committing, update `agent_tasks.commit_hash` for the completed task with the new short hash. This preserves unrelated dirty working-tree state while still producing a verified local commit for the durable ledger note.

## Pitfalls observed

- The visible progress ledger may reference `universe`/`universe_symbols`; ad-hoc KPI SQL using a guessed table name such as `universe_tickers` can fail. Inspect `information_schema.columns`/known live schema before calculating metrics, then rerun the insertion before task completion.
- If metric insertion fails after task/run creation, fix and rerun the KPI insertion, then only mark the task/run complete after confirming `loop_metrics` row count for the run.
- A later verification rerun of `budget_gate.py` can show a higher `tokens_today` than the original Phase 0 value because other cron jobs continue running. Store the original blocker value in the task metadata/ledger and mention the later value only as current state.

## Verification checklist

1. `budget_gate.py --no-record` blocks with exit `1`.
2. `config_guardian.py` exits `0` and reports no probation or an understood probation state.
3. `hermes cron list` exits `0` and the optimizer job remains active/enabled.
4. Postgres confirms task/run status and verification fields:
   ```sql
   select id,status,verification_result is not null,commit_hash from agent_tasks where id=<task_id>;
   select id,status,records_created,summary from agent_runs where id=<run_id>;
   select count(*) from loop_metrics where run_id=<run_id>;
   ```
5. If committing, verify `git diff --cached` contains only the intended ledger hunk before `git commit`.
