# Wolfy plan-only budget-gate token-cap run — 2026-07-31

Session pattern for the daily Wolfy optimizer when the proactive budget gate blocks implementation.

## Verified commands/output

- `python3 wolfy/guardian/budget_gate.py --no-record` -> `BUDGET=block token_cap_exceeded tokens_today=287364 cap=200000`, exit `1`.
- `python3 wolfy/guardian/config_guardian.py` -> `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;hermes_cron_list_ok;no_probation`, exit `0`.
- `hermes cron list` succeeded; optimizer job `92f31b95fccc` stayed active and unchanged.
- Durable state written: `agent_tasks.id=3651`, `agent_runs.id=372419`, `loop_metrics` count for run = `21`.
- Narrow verified ledger commit: `d096cb3 wolfy(opt): record budget-blocked optimizer run — DoD met (task 3651)`.

## Durable lessons

- `cron/jobs.json` may be a top-level object with keys `jobs` and `updated_at`, not a bare list. Parse defensively:
  ```python
  obj = json.loads(Path('cron/jobs.json').read_text())
  jobs = obj.get('jobs', []) if isinstance(obj, dict) else obj
  ```
  Otherwise quick orientation snippets that iterate `for j in jobs` can fail with `'str' object has no attribute 'get'`.
- Keep using plain `budget_gate.py --no-record` and bare `config_guardian.py`; do not invent `--json`, `--health-json`, or `--status` flags.
- If `agent_tasks.source_fingerprint` lacks a unique constraint, dedupe by `SELECT` then `UPDATE`/`INSERT`, not `INSERT ... ON CONFLICT (source_fingerprint)`.
- For a verified plan-only ledger-only change, it is acceptable to make a narrow local commit after checking that only the intended ledger file is staged; store the commit hash back on the task.
- Record `jobs_skipped_by_budget=1` and finish the plan-only run as `completed` only when durable progress exists (task/run/metrics/ledger). Use `blocked` if no durable progress was made.

## Report shape used

Final cron response stayed compact:

- `CHANGED`: plan-only/no implementation, durable state, ledger commit.
- `VERIFIED`: budget gate, guardian, cron list, commit hash.
- `KPI/STATE`: headroom/skipped/gateway/probation/current caps.
- `BLOCKED/HUMAN ASK`: Tier B only.
- `NEXT ACTION`: OWS-4 Jonah cadence when budget recovers.
