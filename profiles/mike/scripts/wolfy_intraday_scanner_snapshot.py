#!/usr/bin/env python3
"""Hermes no_agent wrapper for Wolfy's silent intraday scanner snapshot."""
from __future__ import annotations

import sys
from pathlib import Path

WOLFY_DIR = Path('/root/.hermes/wolfy')
sys.path.insert(0, str(WOLFY_DIR))

from intraday_scanner_snapshot import main  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main())
