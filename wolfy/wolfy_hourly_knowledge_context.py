#!/usr/bin/env python3
"""Compatibility wrapper for Jonah's hourly/autonomous knowledge context.

Older diagnostics may still call wolfy_hourly_knowledge_context.py directly;
the live implementation is hourly_knowledge_context.py.
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

WOLFY_DIR = Path(__file__).resolve().parent
if str(WOLFY_DIR) not in sys.path:
    sys.path.insert(0, str(WOLFY_DIR))

runpy.run_path(str(WOLFY_DIR / 'hourly_knowledge_context.py'), run_name='__main__')
