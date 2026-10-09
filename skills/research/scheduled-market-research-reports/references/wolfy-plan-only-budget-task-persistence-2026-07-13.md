# Wolfy plan-only budget-gated optimizer run — 2026-07-13

## Context

Daily Wolfy optimizer ran while the proactive budget gate was already installed. The gate blocked implementation because token usage was above the configured cap:

```bash
python wolfy/guardian/budget_gate.py --no-record || true
# BUDGET=block token_cap_exceeded tokens_today=293918 cap=200000
```

Because budget was blocked, no code/config/cron change was made and no local commit was created.

## Useful pattern

Even in a budget-gated plan-only run, keep the durable orchestration loop useful by doing deterministic, low-token state updates:

1. Run orientation from deterministic sources: ET time, git status, `hermes cron list`, process list, budget gate, guardian, visible ledger, open `agent_tasks`, probation marker, and optimizer TODO tail.
2. If budget gate returns `BUDGET=block`, stop implementation immediately. Do **not** touch code, cron schedules, config, LLM job enablement, or strategy state.
3. Persist the next concrete task instead of only reporting a roadmap. Example from this run:
   - `agent_tasks.id=3546`
   - title: `OWS-4 — Right-size Jonah cadence outlier`
   - status: `queued`
   - DoD includes snapshot, single Jonah schedule change, YAML parse, `hermes cron list`, cadence/`next_run_at` verification, probation marker, and lower LLM-call projection.
4. Create and finish an `agent_runs` row for the optimizer iteration as `completed` when deterministic plan/state/metrics work was successfully written, with a summary that says `Plan-only due to budget gate block`. Use `blocked` only when the run failed to make even that durable state update or when policy requires a blocked status for the specific row.
5. Record `loop_metrics` despite plan-only mode: at minimum `jobs_skipped_by_budget=1`, `usage_headroom_pct`, `tokens_today`, `gateway_healthy`, `config_rollbacks`, `max_turns`, `parallel_jobs_cap`, `human_approval_pending`, and strategy candidate/approved counts.
6. Final report should be concise: CHANGED / VERIFIED / KPI/STATE / BLOCKED-HUMAN ASK / NEXT ACTION.

## Command/schema pitfalls discovered

- `wolfy/guardian/budget_gate.py` does **not** support `--json`; use plain output plus `--no-record` when you do not want extra metric writes.
- `wolfy/guardian/config_guardian.py` does **not** support `--health --json`; use `python wolfy/guardian/config_guardian.py --skip-cli` for a cheap health check or import `health()` for structured checks.
- Visible ledger path is `/root/.hermes/wolfy/visible_progress_ledger.py`, not `/root/.hermes/scripts/visible_progress_ledger.py`.
- Current `loop_metrics` schema uses `metric_key`, not `metric_name`.
- Current `agent_runs` has `error_message`, not `error`; it also has `ended_at`/`finished_at` compatibility columns.
- Postgres `%` literals inside psycopg SQL strings need escaping or parameters; a query containing `ILIKE '%optimization%'` must pass the pattern as a parameter rather than embedding `%o`, which psycopg treats as an invalid placeholder.

## Verification outputs from the run

```bash
python wolfy/guardian/config_guardian.py --skip-cli || true
# GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;no_probation

hermes cron list
# optimizer job active, schedule 15 2 * * *, next run 2026-07-14T02:15:00-04:00

# Postgres verification confirmed:
# TASK [3546, "OWS-4 — Right-size Jonah cadence outlier", "queued", ...]
# RUN [303740, "completed", "Plan-only due to budget gate block; ...", records_created=14, ...]
# 13 loop_metrics rows for run_id=303740
```
