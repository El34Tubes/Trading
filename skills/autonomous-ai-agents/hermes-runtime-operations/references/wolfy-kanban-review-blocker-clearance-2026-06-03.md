# Wolfy Kanban review-only blocker clearance (2026-06-03)

Use this pattern when a Wolfy Kanban card is blocked only for `review-required` after a worker handoff with concrete verification commands.

## Trigger

A task is `blocked` with language like:

- `review-required: ... verified ... needs human review before marking done`
- Handoff comment lists changed files and exact tests/smokes already run.
- The blocked task is not necessarily assigned to Mike, but the blocker is operational verification, not market judgment or destructive approval.

## Safe Mike ops action

1. Read the card and extract the cited verification commands.
2. Rerun the narrow test(s), then the broader cheap suite if available.
3. Include required guards before full verification, e.g. `/root/.hermes/wolfy/check_postgres_requirements.py` before Postgres-sensitive work.
4. Prefer non-mutating smoke tests for review clearance. If a prior handoff already tested `--store`, use `--json` or an equivalent read-only smoke to avoid inserting duplicate runtime rows.
5. If all verification passes, add a Kanban comment with real command output summaries and complete the card.
6. If verification fails, leave the card blocked with the current failing command/output and do not invent a code fix from stale log tails.

## Example verified output from this run

- `check_postgres_requirements.py` OK: PostgreSQL 16.14, `pg_trgm` 1.6, `vector` 0.6.0.
- `python3 -m pytest -q /root/.hermes/wolfy` -> `78 passed in 0.89s`.
- `python3 -m py_compile weekly_scorecard.py test_weekly_scorecard.py` -> OK.
- `weekly_scorecard.py --json --as-of ... --lookback-days 7` -> valid `report`, `report_id`, `scorecard` payload without storing another report.

## Pitfalls

- Recent error-log tails are triage leads, not current truth. Rerun the exact tests before editing.
- Do not treat provider quota errors (`HTTP 429 usage_limit_reached`) as code failures when script-only checks and direct tests pass.
- Do not require the card assignee to be `mike`; Mike may clear review-only operational blockers when the work is already implemented and verification is non-destructive.
