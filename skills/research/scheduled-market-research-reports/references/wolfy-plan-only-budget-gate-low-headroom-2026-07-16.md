# Wolfy plan-only optimizer budget gate — 2026-07-16

## Trigger

Daily Wolfy optimizer run at 02:16 ET found proactive budget gate over cap:

```text
python3 /root/.hermes/wolfy/guardian/budget_gate.py
BUDGET=block token_cap_exceeded tokens_today=276666 cap=200000
exit=1
```

Per the Wolfy self-optimizing loop rules, this forces **PLAN-ONLY**: deterministic orientation/review/state/KPI updates only; no implementation, no code edits beyond allowed ledger/state notes, no config/cron changes, no new probation marker.

## Verified sequence

1. Orient with deterministic checks: ET/UTC time, `git status --porcelain`, `hermes cron list`, process snapshot, visible progress ledger, open `agent_tasks`, probation marker, and tail of `optimization_todo.md`.
2. Run the guardian using its supported CLI shape:
   ```text
   python3 /root/.hermes/wolfy/guardian/config_guardian.py
   GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;hermes_cron_list_ok;no_probation
   exit=0
   ```
   Do **not** use unsupported flags such as `--check`, `--status`, `--health`, or `--health-json` unless the script has been changed and verified.
3. Confirm `hermes cron list` succeeds and optimizer job `92f31b95fccc` remains active.
4. If a concrete next task already exists (here queued task `3546`, OWS-4 Jonah cadence), do not create a duplicate plan-only task just to show work. Start/finish an `agent_runs` row for the optimizer run and record metrics instead.
5. Record `loop_metrics` for the run. In this run useful rows included: `tokens_today=276666`, `usage_headroom_pct=0`, `jobs_skipped_by_budget=1`, `gateway_healthy=1`, `config_rollbacks=0`, `max_turns=90`, `parallel_jobs_cap=1`, `freshness_core_pct`, `depth_ready_pct`, `iteration_success_rate`, `human_approval_pending`, strategy counts, and repo size.
6. Append a concise dated note to `/root/.hermes/wolfy/optimization_todo.md` with budget result, guardian/probation result, durable state updates, and the next action.
7. Finish the optimizer run as completed only if durable state was updated:
   ```text
   python3 /root/.hermes/wolfy/wolfy_agent_cli.py run-finish \
     --run-id <id> --status completed \
     --summary "Plan-only optimizer run completed: budget gate blocked implementation; guardian/cron healthy; no probation; KPIs and ledger recorded."
   ```

## Pitfalls captured

- `config_guardian.py --check` is invalid; the script's supported invocation is bare `config_guardian.py`, `--skip-cli`, or `--snapshot` depending on the validation need.
- Plan-only does not require inventing a new duplicate `agent_task` when the next OWS task is already queued with a DoD.
- When over cap, report `usage_headroom_pct=0` rather than a negative operational headroom value unless a downstream metric explicitly expects signed overage.
- Do not make a local commit for a small ledger-only update during a budget-blocked run unless the prompt/run explicitly requires it and staged paths are clean.

## Final report shape used

```text
CHANGED
- Plan-only run: budget gate blocked implementation (...), so no code/config/cron orchestration changes.
- Recorded durable state: Postgres run <id>, loop_metrics rows, and optimization_todo.md entry.

VERIFIED
- hermes cron list succeeded; optimizer active.
- config_guardian.py -> GUARDIAN=ok ... no_probation.
- budget_gate.py -> BUDGET=block ...
- No commit made: budget-blocked plan-only/state-update run.

KPI/STATE
- Key budget, guardian, depth, strategy, and approval state.

BLOCKED/HUMAN ASK
- None.

NEXT ACTION
- Execute queued OWS-4 Jonah cadence change when budget recovers.
```
