# Wolfy plan-only budget gate token cap — 2026-08-05

## Trigger

Daily Wolfy optimizer ran at 2026-08-05 02:15 ET / 06:15 UTC. The proactive budget gate blocked implementation:

```text
python3 wolfy/guardian/budget_gate.py --no-record
BUDGET=block token_cap_exceeded tokens_today=241183 cap=200000
exit 1
```

## Correct workflow

When the budget gate blocks, do **not** attempt Tier S implementation, code edits, config edits, cron changes, or LLM-job enablement. Perform a bounded plan-only loop:

1. Verify guardian and scheduler health:
   - `python3 wolfy/guardian/config_guardian.py`
   - `hermes cron list`
2. Confirm no probation marker is pending/expired.
3. Create/claim an `agent_tasks` row for the plan-only run with a stable source fingerprint.
4. Open/finish an `agent_runs` row for the optimizer run.
5. Record small KPI rows (`tokens_today`, `usage_headroom_pct=0`, `jobs_skipped_by_budget=1`, `gateway_healthy`, `config_rollbacks`, `max_turns`, `parallel_jobs_cap`, `human_approval_pending`, etc.).
6. Update `wolfy/optimization_todo.md` with a concise entry and the next concrete action.
7. Send the short cron completion report; no commit is needed if only plan-only state/ledger was updated and repo already has unrelated dirty changes.

## Verification facts from this run

- `config_guardian.py` returned: `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;hermes_cron_list_ok;no_probation`.
- `hermes cron list` succeeded and optimizer job `92f31b95fccc` remained active, next run `2026-08-06T02:15:00-04:00`.
- Postgres task `3691` completed with DoD/verification populated.
- Postgres run `379948` completed with summary `PLAN-ONLY budget block: token cap exceeded; no implementation; guardian/cron healthy; KPIs and ledger updated.`
- 11 KPI rows were recorded; notable values: `tokens_today=241183`, `usage_headroom_pct=0`, `jobs_skipped_by_budget=1`, `gateway_healthy=1`, `config_rollbacks=0`, `max_turns=90`, `parallel_jobs_cap=1`, `human_approval_pending=0`, trailing 7d success ≈ `0.993`.

## Pitfalls reinforced

- Do not read `agent_runs.error`; current schema uses `error_message`. If an orientation query fails inside a psycopg transaction, the remaining statements in that transaction will be aborted — retry with autocommit or a fresh connection.
- `loop_metrics` canonical inserts should use `metric_key`; `metric_name` may exist as a compatibility alias.
- This repo is often dirty from curator/profile/autorepair activity. A plan-only ledger update should not blindly stage or commit broad repo changes.

## Next action preserved

When budget headroom recovers, execute exactly one Tier S slice: queued task `3546` / OWS-4, reducing Jonah cadence from `*/20` to hourly under the self-modification protocol.