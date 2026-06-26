# Wolfy Jonah hourly context wrapper preservation — 2026-06-19

## Trigger

Mike autonomous environment triage showed a recent cron/tool error:

```text
python3: can't open file '/root/.hermes/wolfy/wolfy_hourly_knowledge_context.py': [Errno 2] No such file or directory
```

The live implementation was `/root/.hermes/wolfy/hourly_knowledge_context.py`, while default-profile cron and some diagnostics still referenced the legacy prefixed name `wolfy_hourly_knowledge_context.py`.

## Safe fix pattern

Use the standard Wolfy wrapper-preservation pattern rather than renaming the live implementation or changing cron immediately:

1. Add a tiny compatibility wrapper at all invocation layers:
   - `/root/.hermes/wolfy/wolfy_hourly_knowledge_context.py`
   - `/root/.hermes/scripts/wolfy_hourly_knowledge_context.py`
   - `/root/.hermes/profiles/mike/scripts/wolfy_hourly_knowledge_context.py`
   - `/root/.hermes/profiles/clerky/scripts/wolfy_hourly_knowledge_context.py`
2. Patch the canonical `/root/.hermes/scripts/mike_safe_autorepair.py` first so the wrapper survives future autorepair/self-sync runs:
   - include `wolfy_hourly_knowledge_context.py` in the Mike and Clerky profile sync allowlists;
   - add it to `LEGACY_WRAPPERS` for the global scripts wrapper;
   - add it to `LEGACY_WOLFY_WRAPPERS` for the Wolfy-local wrapper.
3. Run autorepair twice. The first run should report the writes/syncs; the second should be silent.

## Wrapper body

Global/profile wrapper form:

```python
#!/usr/bin/env python3
"""Compatibility wrapper for Jonah's hourly/autonomous knowledge context."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

WOLFY_DIR = Path('/root/.hermes/wolfy')
if str(WOLFY_DIR) not in sys.path:
    sys.path.insert(0, str(WOLFY_DIR))

runpy.run_path(str(WOLFY_DIR / 'hourly_knowledge_context.py'), run_name='__main__')
```

Wolfy-local wrapper form can use `Path(__file__).resolve().parent` for `WOLFY_DIR`.

## Verification commands

Compile exact wrappers and autorepair copies:

```bash
python3 -m py_compile \
  /root/.hermes/scripts/mike_safe_autorepair.py \
  /root/.hermes/wolfy/mike_safe_autorepair.py \
  /root/.hermes/scripts/wolfy_hourly_knowledge_context.py \
  /root/.hermes/wolfy/wolfy_hourly_knowledge_context.py \
  /root/.hermes/profiles/mike/scripts/wolfy_hourly_knowledge_context.py \
  /root/.hermes/profiles/clerky/scripts/wolfy_hourly_knowledge_context.py
```

Smoke the context without claiming work or opening a run:

```bash
psql -d wolfy -Atc "select 'before_started='||count(*) from agent_runs where status='started'; select 'before_in_progress='||count(*) from agent_tasks where status='in_progress';"
WOLFY_CONTEXT_SMOKE=1 python3 /root/.hermes/wolfy/wolfy_hourly_knowledge_context.py >/tmp/wolfy_hourly_smoke.out
psql -d wolfy -Atc "select 'after_started='||count(*) from agent_runs where status='started'; select 'after_in_progress='||count(*) from agent_tasks where status='in_progress';"
```

Expected: output includes `SMOKE=true; no task claimed and no agent_run opened`, and before/after counts are unchanged.

Then verify usual Mike ops health:

```bash
python3 /root/.hermes/wolfy/check_postgres_requirements.py
python3 /root/.hermes/scripts/wolfy_embed_knowledge_chunks.py >/tmp/embed_smoke.out
python3 /root/.hermes/scripts/wolfy_cleanup_stale_agent_coordination.py >/tmp/cleanup_smoke.out
python3 /root/.hermes/scripts/wolfy_usage_limit_watchdog.py >/tmp/usage_watchdog_1.out
python3 /root/.hermes/scripts/wolfy_usage_limit_watchdog.py >/tmp/usage_watchdog_2.out
hermes --profile default cron list --all
```

## Reporting nuance

- Treat aggregate usage snapshot threshold output as usage-volume context unless the dedicated usage-limit watchdog emits twice or logs show active quota/rate-limit events.
- A currently running Mike cron row may legitimately appear as one `agent_runs.status='started'`; do not classify it as stale without age/context checks.
- Credential/API warnings from `hermes doctor` are setup-needed, not environment breakage, when the production path is otherwise authenticated and cron jobs are running.
