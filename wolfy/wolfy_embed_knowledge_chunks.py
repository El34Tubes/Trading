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
