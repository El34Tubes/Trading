# Wolfy embedding legacy wrapper + autorepair pattern (2026-06-01)

## Trigger

Use this when a Wolfy/Mike ops diagnostic or cron log reports a missing legacy script path like:

```text
python3: can't open file '/root/.hermes/wolfy/wolfy_embed_knowledge_chunks.py': [Errno 2] No such file or directory
```

The live embedding implementation may have been renamed to:

```text
/root/.hermes/wolfy/embed_knowledge_chunks.py
```

Do **not** treat this as an embedding-system failure if the live implementation and cron wrapper still work. Preserve compatibility for older diagnostics/wrappers.

## Safe fix

Create `/root/.hermes/wolfy/wolfy_embed_knowledge_chunks.py` as a deterministic compatibility wrapper:

```python
#!/usr/bin/env python3
"""Compatibility wrapper for the Wolfy knowledge embedding sync.

Some diagnostics and older cron/context snippets refer to this legacy filename;
the live implementation is embed_knowledge_chunks.py.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name('embed_knowledge_chunks.py')

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, str(SCRIPT), '--limit', '200', *sys.argv[1:]]))
```

Then `chmod +x` it.

## Make the fix durable

Patch `/root/.hermes/wolfy/mike_safe_autorepair.py` so the script-only autorepair loop recreates the compatibility wrapper if it disappears. Keep the synced copy at `/root/.hermes/scripts/mike_safe_autorepair.py` identical.

Pattern:

```python
LEGACY_WOLFY_WRAPPERS = {
    'wolfy_embed_knowledge_chunks.py': """...wrapper content...""",
}

# inside sync_scripts()
for name, content in LEGACY_WOLFY_WRAPPERS.items():
    dest = WOLFY / name
    if not dest.exists() or dest.read_text() != content:
        dest.write_text(content)
        dest.chmod(0o755)
        changed.append(f'WROTE_LEGACY_WOLFY_WRAPPER {dest}')
```

## Verification commands

Run real verification before reporting the repair:

```bash
python3 -m py_compile /root/.hermes/wolfy/mike_safe_autorepair.py /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/wolfy/wolfy_embed_knowledge_chunks.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py
cd /root/.hermes/wolfy && python3 -m pytest -q test_agent_coordination_smoke.py tests/test_embed_knowledge_chunks.py
/root/.hermes/wolfy/check_postgres_requirements.py
hermes --profile default cron list --all
```

For no-agent watchdog/helper scripts, empty stdout with exit code 0 is a healthy silent run. In the observed repair, these helpers produced zero bytes and succeeded:

```text
wolfy_embed_compat: 0 bytes
stale_coordination_cleanup: 0 bytes
usage_snapshot: 0 bytes
```

## Reporting guidance

Report the compatibility wrapper and autorepair hardening as the fix. Do not say embeddings were broken if `knowledge_chunks` and `embedding` counts match and the live script succeeds.
