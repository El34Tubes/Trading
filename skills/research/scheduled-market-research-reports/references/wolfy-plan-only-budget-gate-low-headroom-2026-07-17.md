# Wolfy plan-only budget gate run — 2026-07-17

## Context

Daily Wolfy optimizer ran under the self-optimizing control-plane prompt with budget headroom exhausted.

- Budget check: `python3 wolfy/guardian/budget_gate.py --no-record` returned `BUDGET=block token_cap_exceeded tokens_today=270998 cap=200000`, exit `1`.
- Guardian check: `python3 wolfy/guardian/config_guardian.py` returned `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;hermes_cron_list_ok;no_probation`.
- Cron check: `hermes cron list` succeeded; optimizer and config guardian remained active.
- Visible ledger: `python3 wolfy/visible_progress_ledger.py --json` succeeded.

## Durable state pattern

Even when implementation is blocked by the budget gate, make a small deterministic state update if cheap and safe:

1. Create/claim a plan-only `agent_tasks` row with a stable source fingerprint.
2. Open an `agent_runs` row for the optimizer iteration.
3. Record `loop_metrics` rows for the current run: token/headroom, budget skip, guardian/gateway health, config rollbacks, max turns/concurrency cap, human-approval count, strategy counts, data freshness/depth, repo size, and migration posture.
4. Complete the task/run as `completed` only if the review/state/KPI update actually succeeded; otherwise mark blocked/failed.
5. Update `optimization_todo.md` with the shortest useful ledger entry.
6. If the only file change is the verified ledger entry, a narrow local commit is acceptable after verifying staged paths.

Concrete row IDs from this run: task `3569`, run `319202`, local commit `49f597b`.

## Pitfalls discovered

- `visible_progress_ledger.py` lives at `wolfy/visible_progress_ledger.py`, not `scripts/visible_progress_ledger.py`.
- For current Wolfy Postgres schema, use table `universe` for active/enabled ticker counts; do not query a nonexistent `tickers` table when recording data-health KPIs.
- The current `agent_tasks` schema has `metadata` JSONB; if there are no dedicated `commit_hash`/verification columns, storing `commit_hash` in `metadata` is a working pattern. Do not assume `payload` is the only JSONB metadata field.
- If a metrics insertion script fails partway, rerun an idempotent focused metrics/update script and then re-check `loop_metrics where run_id=<id>`, `agent_runs.status/records_created`, and `agent_tasks.status/definition_of_done`.
- In dirty Hermes repos, always commit with an explicit path (`git add wolfy/optimization_todo.md`) and verify staged paths; do not stage broad profile/curator/autorepair drift.

## Final report shape used

Keep the cron final concise:

- `CHANGED`: plan-only reason, durable state, local commit.
- `VERIFIED`: exact budget/guardian/cron/ledger commands and statuses.
- `KPI/STATE`: only notable values (`usage_headroom_pct=0`, `jobs_skipped_by_budget=1`, etc.).
- `BLOCKED/HUMAN ASK`: only Tier B asks; here none.
- `NEXT ACTION`: one concrete queued control-plane slice (`OWS-4`, Jonah cadence hourly) once budget recovers.
