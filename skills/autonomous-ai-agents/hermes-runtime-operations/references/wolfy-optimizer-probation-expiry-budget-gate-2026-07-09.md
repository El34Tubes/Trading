# Wolfy optimizer probation expiry at scheduled run boundary (2026-07-09)

## Situation

A Wolfy optimizer run started at the same boundary as a prior self-modification probation expiry. The deterministic `config_guardian.py` had already restored the latest known-good snapshot and cleared `wolfy/guardian/probation.json` because the marker expired before the optimizer could confirm it.

The budget gate also reported over-cap:

```text
BUDGET=block token_cap_exceeded tokens_today=279759 cap=200000
```

Per Wolfy rules, the optimizer stayed plan-only: no code/config/cron changes.

## Important lesson

Do **not** automatically treat a probation-expiry restore as a functional regression. First verify whether the intended protected behavior survived in the latest known-good snapshot.

In this run, the Jonah context budget gate was still present after restore. The correct verification was:

```bash
python3 scripts/wolfy_hourly_knowledge_context.py
```

Expected blocked-path output:

```text
skipped: budget BUDGET=block ...
{"wakeAgent": false, "reason": "budget"}
```

Exit code should be 0 so cron no-ops cleanly without spending LLM tokens.

## Safe plan-only handling pattern

1. Run `wolfy/guardian/budget_gate.py` first.
2. If blocked, do not implement or modify orchestration/config.
3. Run `config_guardian.py --skip-cli` or full guardian health check and verify `no_probation` / known state.
4. If guardian restored at the run boundary, inspect the affected behavior directly before declaring rollback/regression.
5. Record a plan-only `agent_task`, `agent_run`, and `loop_metrics` rows (`jobs_skipped_by_budget`, `tokens_today`, `usage_headroom_pct`, `config_rollbacks`, `gateway_healthy`, `parallel_jobs_cap`, `max_turns`).
6. Update `optimization_todo.md` with the lesson and next action, but do not commit when there is broad pre-existing dirty state and no verified implementation change.

## Future improvement candidate

If repeated false rollbacks occur because optimizer probation expiry equals scheduled start time, consider a bounded guardian change to add a small confirmation grace window. That would be a self-modification-protocol change: snapshot, apply one reversible change, validate, probation marker, next-run confirmation.
