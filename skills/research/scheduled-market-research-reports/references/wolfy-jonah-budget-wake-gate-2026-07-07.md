# Wolfy Jonah budget wake-gate slice — 2026-07-07

Session-specific learning from a Wolfy daily optimizer run that implemented a bounded OWS-1 slice for Jonah.

## What changed

- Patched cron-facing wrapper `/root/.hermes/scripts/wolfy_hourly_knowledge_context.py` to call `/root/.hermes/wolfy/guardian/budget_gate.py --no-record` before running Jonah context generation.
- If the budget gate blocks, the wrapper exits 0 after printing:
  - human line: `skipped: budget BUDGET=block ...`
  - final machine line: `{"wakeAgent": false, "reason": "skipped: budget"}`
- Cron's scheduler parses the final non-empty JSON line and skips the LLM call; this is the actual token-saving gate.
- If the gate passes, the wrapper runs `hourly_knowledge_context.py` normally, including `WOLFY_CONTEXT_SMOKE=1` smoke mode.

## Verification commands that mattered

```bash
python -m py_compile scripts/wolfy_hourly_knowledge_context.py
WOLFY_BUDGET_SIMULATED_TOKENS_TODAY=999999 WOLFY_BUDGET_IGNORE_AUTH=1 python scripts/wolfy_hourly_knowledge_context.py
WOLFY_CONTEXT_SMOKE=1 WOLFY_BUDGET_IGNORE_AUTH=1 python scripts/wolfy_hourly_knowledge_context.py
python - <<'PY'
import json, yaml
from pathlib import Path
yaml.safe_load(Path('config.yaml').read_text())
json.loads(Path('cron/jobs.json').read_text())
print('config_yaml_ok jobs_json_ok')
PY
hermes cron list
python wolfy/guardian/config_guardian.py --skip-cli
```

Expected over-cap output includes `skipped: budget` and the final `wakeAgent=false` JSON, with exit 0. Expected normal smoke output includes `BUDGET=ok` and Jonah context, without opening live started rows when `WOLFY_CONTEXT_SMOKE=1` is set.

## Pitfalls

- A budget gate script existing is not OWS-1 completion; every LLM cron job must consult it before LLM spend or emit a scheduler wake gate.
- Do not put the check only in the prompt: the LLM has already been called by then.
- Put the check before context-generation side effects such as `claim_next_task()` / `start_agent_run()` where possible.
- Wolfy's config guardian expects probation marker keys `created_at` and `expires_at`. Using `created_at_utc` / `expires_at_utc` caused `probation_missing_expiry` and a known-good restore. Fix the marker then re-run guardian until it reports `probation_active`.
- If guardian restores config/jobs while preserving a non-config wrapper edit, revalidate rather than assuming the whole change was rolled back.

## State from this slice

- Task: `agent_tasks.id=3405`
- Run: `agent_runs.id=250505`
- Commit: `0ac756c`
- Probation expiry: `2026-07-08T06:15:00Z`
