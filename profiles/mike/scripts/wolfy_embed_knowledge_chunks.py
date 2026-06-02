#!/usr/bin/env python3
"""Compatibility wrapper for Wolfy's knowledge embedding sync.

Cron/profile wrappers and older diagnostics may still call this legacy name;
the live implementation is /root/.hermes/wolfy/embed_knowledge_chunks.py.
"""
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/wolfy/embed_knowledge_chunks.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, '--limit', '200', *sys.argv[1:]]))
