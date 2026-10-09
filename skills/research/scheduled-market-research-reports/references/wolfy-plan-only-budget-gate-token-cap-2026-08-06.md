# Wolfy plan-only budget gate token-cap run — 2026-08-06

## Trigger

Daily Wolfy optimizer ran under the self-optimizing loop while the proactive budget gate was already over the configured daily token cap.

## Deterministic orientation facts

- ET time: `2026-08-06 02:15 EDT`.
- Optimizer job: `92f31b95fccc` remained active; `hermes cron list` succeeded.
- Budget check: `python3 wolfy/guardian/budget_gate.py --no-record` returned `BUDGET=block token_cap_exceeded tokens_today=397910 cap=200000` with exit 1.
- Guardian check: `python3 wolfy/guardian/config_guardian.py --skip-cli` returned `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;no_probation` with exit 0.
- No probation marker existed; `config.yaml` and `cron/jobs.json` parsed successfully.

## Action pattern

When the budget gate blocks:

1. Do not implement code/config/cron changes and do not attempt an orchestration self-modification.
2. Still complete deterministic state maintenance:
   - persist/claim/complete a plan-only `agent_tasks` row;
   - start/finish a matching `agent_runs` row;
   - record `loop_metrics` for budget state, guardian health, config rollbacks, max turns, concurrency cap, loop health, and strategy counts;
   - update `wolfy/optimization_todo.md` with a concise daily entry.
3. Final report should be short: changed/state, exact verification commands, KPI rows, no new human asks, and the next OWS action.

## Persisted result

- `agent_tasks.id=3701`, completed with verification text containing budget, guardian, and cron-list results.
- `agent_runs.id=381140`, completed with `records_created=13`.
- Recorded 13 `loop_metrics` rows, including:
  - `tokens_today=397910`
  - `usage_headroom_pct=0`
  - `jobs_skipped_by_budget=1`
  - `gateway_healthy=1`
  - `config_rollbacks=0`
  - `max_turns=90`
  - `parallel_jobs_cap=1`
  - `human_approval_pending=0`
  - `strat_candidate=2`
  - `strat_approved=0`

## Pitfalls confirmed

- `budget_gate.py` does not have `--json`; use plain stdout and `--no-record` for no-extra-write checks.
- `config_guardian.py` does not have `--check --json`; use `--skip-cli` for a cheap health check or bare invocation for the full check.
- The repo can be broadly dirty from unrelated profile/curator/autorepair files; do not commit a plan-only ledger update unless staged paths are inspected and intentionally narrow.

## Next action left queued

Preferred next bounded Tier S slice remains `agent_tasks.id=3546` / OWS-4: reduce Jonah cadence from `*/20` to hourly under the self-modification protocol once budget headroom recovers.