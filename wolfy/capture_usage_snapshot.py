#!/usr/bin/env python3
"""Capture Hermes usage totals into Wolfy's Postgres usage snapshot table.

This is aggregate accounting until per-cron-run token metadata is exposed by Hermes.
Silent unless rows are inserted with unusually high cron tokens or an error occurs.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import psycopg

CRON_USAGE_SYNC = Path('/root/.hermes/wolfy/sync_cron_usage_to_agent_runs.py')

DSN = 'dbname=wolfy user=root host=/var/run/postgresql'
DAYS = 1
CRON_TOKEN_NOTICE_THRESHOLD = 2_000_000


def num(s: str | None) -> int | None:
    if not s:
        return None
    return int(s.replace(',', ''))


def platform_row(text: str, name: str) -> tuple[int | None, int | None, int | None]:
    m = re.search(rf'^\s*{re.escape(name)}\s+(\d[\d,]*)\s+(\d[\d,]*)\s+(\d[\d,]*)\s*$', text, re.MULTILINE)
    if not m:
        return None, None, None
    return num(m.group(1)), num(m.group(2)), num(m.group(3))


def main() -> int:
    # Keep per-cron-session agent_runs usage rows current before taking the
    # aggregate insight snapshot. This is best-effort and intentionally silent
    # unless the helper itself errors.
    if CRON_USAGE_SYNC.exists():
        subprocess.check_output(
            ['python3', str(CRON_USAGE_SYNC), '--since-days', '2'],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=180,
        )
    out = subprocess.check_output(['hermes', 'insights', '--days', str(DAYS)], text=True, stderr=subprocess.STDOUT, timeout=120)
    sessions = num((re.search(r'Sessions:\s+(\d[\d,]*)', out) or [None, None])[1])
    messages = num((re.search(r'Messages:\s+(\d[\d,]*)', out) or [None, None])[1])
    tool_calls = num((re.search(r'Tool calls:\s+(\d[\d,]*)', out) or [None, None])[1])
    input_tokens = num((re.search(r'Input tokens:\s+(\d[\d,]*)', out) or [None, None])[1])
    output_tokens = num((re.search(r'Output tokens:\s+(\d[\d,]*)', out) or [None, None])[1])
    total_tokens = num((re.search(r'Total tokens:\s+(\d[\d,]*)', out) or [None, None])[1])
    cron_sessions, cron_messages, cron_tokens = platform_row(out, 'cron')
    cli_sessions, cli_messages, cli_tokens = platform_row(out, 'cli')
    discord_sessions, discord_messages, discord_tokens = platform_row(out, 'discord')
    excerpt = '\n'.join(out.splitlines()[:80])
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_usage_snapshots(
              window_days, sessions, messages, tool_calls, input_tokens, output_tokens, total_tokens,
              cron_sessions, cron_messages, cron_tokens, cli_sessions, cli_messages, cli_tokens,
              discord_sessions, discord_messages, discord_tokens, raw_excerpt)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (DAYS, sessions, messages, tool_calls, input_tokens, output_tokens, total_tokens,
             cron_sessions, cron_messages, cron_tokens, cli_sessions, cli_messages, cli_tokens,
             discord_sessions, discord_messages, discord_tokens, excerpt),
        )
        snapshot_id = cur.fetchone()[0]
    if cron_tokens and cron_tokens >= CRON_TOKEN_NOTICE_THRESHOLD:
        print(f'Wolfy usage snapshot {snapshot_id}: cron tokens over threshold: {cron_tokens:,} in last {DAYS} day(s).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
