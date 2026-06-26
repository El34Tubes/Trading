# Wolfy Kanban review-batch clearance — 2026-06-04

Use when Mike finds multiple Wolfy Kanban cards blocked only on `review-required` after worker handoffs.

## Pattern

1. Inspect each blocker with `hermes kanban --board wolfy show <task_id>` and read the handoff's verification commands.
2. Rerun non-destructive verification, not market logic changes:
   - `/root/.hermes/wolfy/check_postgres_requirements.py`
   - targeted tests cited by the handoff
   - full cheap Wolfy suite when feasible: `cd /root/.hermes/wolfy && python3 -m pytest -q`
   - task-specific read-only or no-persist smoke commands.
3. If a smoke creates an `agent_runs.status='started'` row, close it explicitly with `wolfy_agent_cli.py run-finish --records-created 0` before finishing the review.
4. Comment each card with real command output and a note that no destructive DB/package operations were performed.
5. Complete each reviewed card with the bare command:
   ```bash
   hermes kanban --board wolfy complete <task_id>
   ```
   Do **not** append a free-form summary to `complete`; put the summary in the prior `comment`. Extra words can be parsed as IDs/terminal state and produce confusing output even when completion succeeds.
6. After clearing parent blockers, list and dispatch the board:
   ```bash
   hermes kanban --board wolfy list
   hermes kanban --board wolfy dispatch
   ```
   This promotes/spawns downstream work instead of leaving newly-ready cards idle.

## Example verification bundle from the session

- Postgres guard OK: PostgreSQL 16.14, `pg_trgm 1.6`, `vector 0.6.0`.
- Full Wolfy suite: `78 passed in 0.96s`.
- Targeted review suite: `25 passed in 0.29s`.
- Shared DB adapter smoke: `backend postgres`, `sqlite_fallback_enabled False`, `connected_backend postgres`, destructive guard raised `DestructiveSQLError`.
- Report context dry run: scanner fresh, promotion dry-run `evaluated=10 pending_review=0 watch_only=10`; closed created run with `records_created=0`.
- Scanner no-persist smoke emitted expected factor/reason columns.
- Post-dispatch result: newly-ready downstream card spawned.

## Pitfall

Do not report historical log-tail errors as active blockers if exact reruns now pass. Treat log tails as leads, rerun the relevant tests/smokes, then clear or fix based on current output.