# Wolfy optimizer plan-only budget block — 2026-07-21

## Trigger

Daily Wolfy optimizer ran at 02:15 ET. `budget_gate.py --no-record` returned a low-headroom block rather than an over-cap block:

```text
BUDGET=block low_headroom_pct=12.03 threshold=15.00
exit=1
```

Per Wolfy's optimizer rules, low-headroom blocks are the same as over-cap blocks for implementation purposes: PLAN-ONLY. Do not spend more work on Tier S implementation, config edits, cron schedule edits, migrations, or commits.

## Safe plan-only workflow used

1. Orient cheaply: ET time, `git status --porcelain`, `hermes cron list`, process list, budget gate, config guardian, visible ledger, open Postgres tasks/runs, probation marker, and `optimization_todo.md` tail.
2. Confirm guardian/probation cheaply:
   - `python3 wolfy/guardian/config_guardian.py --skip-cli`
   - expected healthy output: `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;no_probation`.
   - Do not use unsupported `--health-only`.
3. Persist a plan-only task/run:
   - `task-ensure` with stable source fingerprint like `wolfy-optimizer-plan-only-budget-block-YYYY-MM-DD`.
   - update `definition_of_done` in Postgres.
   - `task-claim` and `run-start`.
4. Record deterministic KPI rows before marking the run complete. In this run the useful KPI set included:
   - `tokens_today=175932`
   - `usage_headroom_pct=12.034`
   - `jobs_skipped_by_budget=1`
   - `gateway_healthy=1`
   - `config_rollbacks=0`
   - `max_turns=90`
   - `parallel_jobs_cap=1`
   - `human_approval_pending=0`
   - `iteration_success_rate`
   - repo/migration health spot checks.
5. Mark task and run complete only after querying them back and confirming the KPI count.
6. Update `wolfy/optimization_todo.md` with a concise durable note, but do not treat that note as permission to implement or to make additional repo changes while the budget gate is blocked.

## Verification commands from the run

```bash
python3 wolfy/guardian/budget_gate.py --no-record; echo BUDGET_EXIT=$?
python3 wolfy/guardian/config_guardian.py --skip-cli; echo GUARDIAN_EXIT=$?
hermes cron list >/tmp/wolfy_cron_verify.txt && echo CRON_LIST_OK=1 || echo CRON_LIST_OK=0
```

Expected/result:

```text
BUDGET=block low_headroom_pct=12.03 threshold=15.00
BUDGET_EXIT=1
GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;no_probation
GUARDIAN_EXIT=0
CRON_LIST_OK=1
```

Postgres verification pattern:

```sql
select id,status,verification_result from agent_tasks where id=<task_id>;
select id,status,records_created,summary from agent_runs where id=<run_id>;
select category,metric_key,metric_value from loop_metrics where run_id=<run_id> order by id;
```

## Pitfalls

- A low-headroom block (`headroom_pct < threshold`) is not a soft warning for the optimizer; it is an implementation stop just like `token_cap_exceeded`.
- Keep the run cheap after the block: persist state/KPIs/report only.
- If you use direct psycopg metric insertion, verify row counts before task/run completion; do not leave a completed task with unverified metrics.
- Avoid committing unverified or incidental changes during plan-only blocks. Report no commit unless a verified durable repo change was intentionally made.
