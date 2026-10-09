# Wolfy coordination CLI wrapper preservation (2026-10-01)

## Trigger

A scheduled optimizer called `/root/.hermes/scripts/wolfy_agent_cli.py`, but the canonical implementation existed only at `/root/.hermes/wolfy/wolfy_agent_cli.py`. The optimizer recovered, yet the missing stable path would recur on future runs.

## Safe repair pattern

1. Keep the canonical implementation in the Wolfy directory; do not duplicate its logic.
2. Add a thin executable compatibility wrapper at `/root/.hermes/scripts/wolfy_agent_cli.py` that delegates with the current Python interpreter and forwards all arguments.
3. Add the wrapper definition to canonical `/root/.hermes/scripts/mike_safe_autorepair.py`.
4. Include the wrapper in Mike and Clerky profile synchronization lists so profile-scoped diagnostics and handoffs use the same stable path.
5. Run autorepair twice: the first run may report created/synchronized files; the second must be silent.
6. Compile every generated wrapper, run `--help` through the global/Mike/Clerky paths, compare outputs, and verify executable mode (`755`).
7. Recheck Postgres coordination invariants: no stale `agent_runs.status='started'`, no unexpected `agent_tasks.status='in_progress'`, and no embedding gaps.

## Wrapper shape

```python
#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/wolfy/wolfy_agent_cli.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, *sys.argv[1:]]))
```

Delegating by subprocess is appropriate here because running the canonical file directly places its directory on `sys.path`, allowing local imports such as `wolfy_agent_coordination` to resolve naturally.

## Log-triage lesson

Treat an earlier missing-wrapper line as actionable even when the enclosing cron run eventually reports `ok`: recovery does not make the unstable invocation path durable. Conversely, later ad-hoc SQL errors in the same log should not trigger schema changes when the session transcript proves the task/run completed and a follow-up read verified the intended row. Repair the recurring path defect; classify the recovered SQL probe as transient.
