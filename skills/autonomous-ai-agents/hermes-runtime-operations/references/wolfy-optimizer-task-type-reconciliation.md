# Wolfy optimizer task-type reconciliation

Use this note when reviewing the previous Wolfy optimizer closure before creating the current plan-only task.

## Durable lesson

Historical optimizer tasks do not use one stable `task_type` spelling. Live rows have used values including:

- `optimizer_plan_only`
- `optimization_plan_only`
- `optimization`
- `self_optimization`

A filter that includes only the remembered spellings can omit the actual task linked to Git `HEAD`, making an older closure appear current.

## Safe reconciliation

1. Resolve `git rev-parse HEAD`.
2. Query `agent_tasks.commit_hash = <HEAD>` first, regardless of `task_type`.
3. If no exact hash match exists, resolve by the known task ID or unique `source_fingerprint` recorded in the newest ledger entry.
4. Confirm the linked terminal `agent_runs` row, stored Definition of Done, and KPI provenance.
5. Only use a broad `task_type` query as a discovery fallback; include all observed variants and do not treat the result as authoritative until its commit hash matches `HEAD`.

This is especially important during budget-blocked runs: review remains deterministic and cheap, while claiming the queued implementation task is prohibited by the plan-only gate.