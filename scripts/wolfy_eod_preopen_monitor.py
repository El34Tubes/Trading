#!/usr/bin/env python3
"""Silent no-agent pre-open EOD risk monitor.

No stdout unless deterministic checks flag/reject something.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path('/root/.hermes/wolfy/eod_monitoring.py')

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, str(SCRIPT)]))
