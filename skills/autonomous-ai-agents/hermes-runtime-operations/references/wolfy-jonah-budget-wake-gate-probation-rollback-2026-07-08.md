# Wolfy Jonah budget wake-gate after probation rollback (2026-07-08)

## Situation
A prior OWS-1 attempt added a budget wake gate at the Jonah cron wrapper layer. The probation marker expired before confirmation and `config_guardian.py` restored the last known-good snapshot:

```text
GUARDIAN=restored ... probation_expired change=OWS-1 bounded slice: Jonah cron wrapper budget wake gate
```

Treat that exact wrapper-only pattern as a failed implementation pattern; do not reapply it identically.

## Durable fix pattern
For LLM cron jobs with a data-collection/context script, put the deterministic budget gate inside the live context implementation before any task claim, `agent_runs` start, or context output that would feed the LLM. For Jonah, this meant adding the gate to `wolfy/hourly_knowledge_context.py`, not just the compatibility wrapper `scripts/wolfy_hourly_knowledge_context.py`.

Blocked path behavior:

1. Run `wolfy/guardian/budget_gate.py --no-record`.
2. If nonzero or missing, print a human-readable line such as:
   `skipped: budget BUDGET=block ...`
3. Make the final non-empty stdout line JSON:
   `{"wakeAgent": false, "reason": "budget"}`
4. Exit 0 so the scheduler records a clean skipped run and does not spend LLM tokens.

OK path behavior:

- Print the `BUDGET=ok ...` line, then continue normal deterministic context generation.
- In smoke mode (`WOLFY_CONTEXT_SMOKE=1`), emit context without claiming work or opening stale `agent_runs`.

## Self-modification protocol proof commands
Use one reversible slice and snapshot `config.yaml` + `cron/jobs.json` before editing even if the code file is the only touched implementation file.

Verification used:

```bash
python3 -m py_compile wolfy/hourly_knowledge_context.py scripts/wolfy_hourly_knowledge_context.py
WOLFY_BUDGET_SIMULATED_TOKENS_TODAY=999999 WOLFY_BUDGET_IGNORE_AUTH=1 \
  python3 scripts/wolfy_hourly_knowledge_context.py
# expect: skipped: budget ... and final {"wakeAgent": false, ...}, exit 0

WOLFY_CONTEXT_SMOKE=1 WOLFY_BUDGET_IGNORE_AUTH=1 \
  python3 scripts/wolfy_hourly_knowledge_context.py
# expect: Budget gate: BUDGET=ok ..., Jonah context, SMOKE=true, exit 0

python3 - <<'PY'
import json, yaml
yaml.safe_load(open('/root/.hermes/config.yaml'))
json.load(open('/root/.hermes/cron/jobs.json'))
print('config_yaml_ok cron_jobs_json_ok')
PY
hermes cron list
python3 wolfy/guardian/config_guardian.py
# expect GUARDIAN=ok ... probation_active
```

## Reporting/state
- Record the previous rollback in `loop_metrics.config_rollbacks` and `optimization_todo.md`.
- Persist a new probation marker pointing at the current snapshot and expiring at the next expected optimizer run.
- Complete the Postgres `agent_tasks` row only after real command output verifies the skip and OK paths.
