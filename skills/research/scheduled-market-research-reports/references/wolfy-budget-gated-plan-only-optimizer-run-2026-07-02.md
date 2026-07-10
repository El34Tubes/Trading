# Wolfy budget-gated plan-only optimizer run — 2026-07-02

## Context

The daily Wolfy optimizer ran under the self-optimizing control-plane prompt. It had to perform deterministic orientation and respect the low-budget PLAN-ONLY rule before any implementation.

## Observed outputs

- `python /root/.hermes/wolfy/guardian/budget_gate.py --no-record` returned `BUDGET=block token_cap_exceeded tokens_today=840644 cap=200000` with exit 1.
- `python /root/.hermes/wolfy/guardian/config_guardian.py` returned `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;hermes_cron_list_ok;no_probation`.
- `hermes cron list` succeeded.
- `cron/jobs.json` content search showed only the optimizer prompt mentioned `budget_gate`; Jonah and other non-`no_agent` LLM jobs did not contain `budget_gate` or `skipped: budget`.
- Jonah was still scheduled every 20 minutes while the real budget gate was over cap.

## Durable action taken

Because the gate blocked implementation, the run did not edit code/config/cron. It still made deterministic progress:

- Created Postgres `agent_tasks` id `3243`: `Complete OWS-1 budget gate wiring for LLM cron jobs`.
- Recorded Postgres `agent_runs` id `195339`, status completed.
- Recorded loop metrics: `jobs_skipped_by_budget=1`, `usage_headroom_pct=0`, `tokens_today=840644`, `parallel_jobs_cap=1`, `max_turns=90`, `gateway_healthy=1`, `config_rollbacks=0`, `human_approval_pending=0`.
- Appended a short run note to `/root/.hermes/wolfy/optimization_todo.md` and committed it locally as `fcfa404`.

## Lesson / future procedure

A budget-gated plan-only run should not stop after detecting `BUDGET=block`. It should still:

1. Run config guardian and cron-list health checks.
2. Verify whether the previous OWS task is actually wired, not just whether the script exists.
3. If wiring is incomplete, persist a concrete next-action `agent_task` with exact DoD.
4. Record `jobs_skipped_by_budget=1` and relevant state metrics.
5. Update `optimization_todo.md` and final report concisely.

For OWS-1 specifically, completion requires the LLM cron jobs themselves to consult the gate and cleanly no-op with `skipped: budget` before LLM spend. Merely having `wolfy/guardian/budget_gate.py` present is insufficient.
