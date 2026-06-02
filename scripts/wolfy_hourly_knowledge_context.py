#!/usr/bin/env python3
import runpy
import sys
from pathlib import Path

WOLFY_DIR = Path('/root/.hermes/wolfy')
if str(WOLFY_DIR) not in sys.path:
    sys.path.insert(0, str(WOLFY_DIR))

runpy.run_path(str(WOLFY_DIR / 'hourly_knowledge_context.py'), run_name='__main__')
