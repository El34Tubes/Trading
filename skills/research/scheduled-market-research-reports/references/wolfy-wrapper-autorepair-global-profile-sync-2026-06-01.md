# Wolfy wrapper autorepair: global/profile sync nuance (2026-06-01)

Context: Mike triage saw an older log error where diagnostics tried to run `/root/.hermes/wolfy/wolfy_embed_knowledge_chunks.py` after the live implementation had moved to `embed_knowledge_chunks.py`. A local Wolfy compatibility wrapper already existed, but the durable lesson was broader: cron jobs can invoke wrappers from different layers.

## Durable pattern

For renamed Wolfy helper scripts, preserve a tiny compatibility wrapper for the legacy name and verify every invocation layer:

1. Live implementation under `/root/.hermes/wolfy/`, e.g. `embed_knowledge_chunks.py`.
2. Legacy Wolfy wrapper under `/root/.hermes/wolfy/`, e.g. `wolfy_embed_knowledge_chunks.py`.
3. Global cron wrapper under `/root/.hermes/scripts/`, e.g. `wolfy_embed_knowledge_chunks.py`.
4. Profile script wrappers under `/root/.hermes/profiles/<profile>/scripts/`, especially Mike/Clerky/Yang if cron jobs run with `Profile:` set.

A profile wrapper can be healthy while default-profile cron still calls the global wrapper. Do not stop after testing only the profile copy.

## Safe wrapper shape

Prefer absolute-path delegation from global/profile wrappers so the caller's cwd/profile home cannot change behavior:

```python
#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/wolfy/embed_knowledge_chunks.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, '--limit', '200', *sys.argv[1:]]))
```

For a wrapper that lives next to the live implementation, `Path(__file__).with_name('embed_knowledge_chunks.py')` is OK.

## Autorepair requirement

Teach `/root/.hermes/wolfy/mike_safe_autorepair.py` and the global `/root/.hermes/scripts/mike_safe_autorepair.py` copy to recreate the legacy wrappers, then run it once and run it again to confirm it becomes silent.

## Verification commands

```bash
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py  # should be silent
python3 /root/.hermes/scripts/wolfy_embed_knowledge_chunks.py --limit 5
python3 /root/.hermes/profiles/mike/scripts/wolfy_embed_knowledge_chunks.py --limit 5
python3 /root/.hermes/wolfy/wolfy_embed_knowledge_chunks.py --limit 5
python3 -m pytest -q test_agent_coordination_smoke.py tests/test_embed_knowledge_chunks.py
```

Silent exits from the no-agent helpers are healthy unless a wrapper/action prints an actionable alert or exits nonzero.
