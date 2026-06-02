#!/usr/bin/env python3
from pathlib import Path
import runpy

runpy.run_path(str(Path('/root/.hermes/wolfy/sync_cron_usage_to_agent_runs.py')), run_name='__main__')
