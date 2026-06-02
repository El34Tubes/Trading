#!/usr/bin/env python3
"""Allocate worker time to the Wolfy Kanban board.

Safety note: Hermes dispatch can spawn multiple ready tasks in one pass, so this
wrapper first checks board stats. It dispatches only when there are no running
tasks and the ready backlog is small, then passes --max 1 so work is picked off
one card at a time. Otherwise it stays silent, letting the current batch finish
or requiring manual review.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

BOARD = 'wolfy'
MAX_READY_BACKLOG_TO_DISPATCH = 2
MAX_SPAWNS_PER_PASS = 1


def run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT, timeout=120)


def parse_stats(text: str) -> tuple[int, int]:
    ready = running = 0
    for line in text.splitlines():
        m = re.match(r'\s*(ready|running)\s+(\d+)\s*$', line)
        if m:
            if m.group(1) == 'ready':
                ready = int(m.group(2))
            elif m.group(1) == 'running':
                running = int(m.group(2))
    return ready, running


def main() -> int:
    try:
        run(['hermes', 'kanban', 'boards', 'switch', BOARD])
        stats = run(['hermes', 'kanban', 'stats'])
        ready, running = parse_stats(stats)
        if running > 0 or ready == 0:
            return 0
        if ready > MAX_READY_BACKLOG_TO_DISPATCH:
            print(f'Wolfy Kanban allocator holding: {ready} ready tasks exceeds safe backlog cap {MAX_READY_BACKLOG_TO_DISPATCH}; no running tasks. Manual dispatch/reassignment recommended.')
            return 0
        out = run(['hermes', 'kanban', 'dispatch', '--max', str(MAX_SPAWNS_PER_PASS), '--json'])
        data = json.loads(out)
    except subprocess.CalledProcessError as e:
        print('Wolfy Kanban allocator error:')
        print(e.output)
        return e.returncode or 1
    except Exception as e:
        print(f'Wolfy Kanban allocator error: {type(e).__name__}: {e}')
        return 1

    interesting = any([
        data.get('reclaimed'), data.get('crashed'), data.get('timed_out'),
        data.get('stale'), data.get('auto_blocked'), data.get('promoted'),
        data.get('spawned'), data.get('skipped_unassigned'), data.get('auto_assigned_default')
    ])
    if interesting:
        print('Wolfy Kanban allocator update:')
        print(json.dumps(data, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
