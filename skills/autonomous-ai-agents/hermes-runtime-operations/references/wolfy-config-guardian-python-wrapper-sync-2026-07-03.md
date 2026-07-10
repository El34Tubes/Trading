# Wolfy config guardian Python-wrapper sync (2026-07-03)

## Context
Mike ops saw a stale error tail from an LLM triage run:

```text
[Errno 2] No such file or directory: '/root/.hermes/scripts/wolfy_config_guardian.py'
```

The active cron job used `/root/.hermes/scripts/wolfy_config_guardian.sh`, which was healthy and correctly pinned `--home /root/.hermes`. The missing path was an ad-hoc/profile diagnostic expectation for a Python wrapper, not a broken guardian implementation.

## Safe repair pattern

1. Keep the shell cron wrapper stable:
   - `/root/.hermes/scripts/wolfy_config_guardian.sh`
   - It should execute `/root/.hermes/wolfy/guardian/config_guardian.py --home /root/.hermes`.
2. Add a tiny Python compatibility wrapper at:
   - `/root/.hermes/scripts/wolfy_config_guardian.py`
   - `/root/.hermes/profiles/mike/scripts/wolfy_config_guardian.py`
   - `/root/.hermes/profiles/clerky/scripts/wolfy_config_guardian.py`
3. Teach canonical `/root/.hermes/scripts/mike_safe_autorepair.py` to preserve/sync the wrapper by adding `wolfy_config_guardian.py` to both Mike and Clerky profile script allowlists and to `LEGACY_WRAPPERS`.
4. Run autorepair once to sync copies; run it a second time and expect silence.

## Wrapper body

```python
#!/usr/bin/env python3
"""Compatibility wrapper for Wolfy's config guardian.

Profile-scoped Mike cron jobs can inherit HERMES_HOME under the Mike profile,
but this guardian protects the production/default Hermes config and cron files.
Pin --home to /root/.hermes so direct Python probes and the shell wrapper behave
identically.
"""
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/wolfy/guardian/config_guardian.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, '--home', '/root/.hermes', *sys.argv[1:]]))
```

## Verification commands

```bash
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py   # should be silent
HERMES_HOME=/root/.hermes/profiles/mike python3 /root/.hermes/scripts/wolfy_config_guardian.py --skip-cli
HERMES_HOME=/root/.hermes/profiles/mike bash /root/.hermes/scripts/wolfy_config_guardian.sh
python3 -m py_compile \
  /root/.hermes/scripts/wolfy_config_guardian.py \
  /root/.hermes/profiles/mike/scripts/wolfy_config_guardian.py \
  /root/.hermes/profiles/clerky/scripts/wolfy_config_guardian.py \
  /root/.hermes/scripts/mike_safe_autorepair.py \
  /root/.hermes/wolfy/mike_safe_autorepair.py
```

Expected guardian output includes:

```text
GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;no_probation
```

or, for the shell wrapper with CLI enabled:

```text
GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;hermes_cron_list_ok;no_probation
```

## Pitfall
Do not treat the missing Python wrapper as proof that the guardian cron job is broken. First verify the cron-facing `.sh` wrapper. If it is healthy, preserve the `.py` wrapper as diagnostic compatibility and keep both paths pinned to production/default home.