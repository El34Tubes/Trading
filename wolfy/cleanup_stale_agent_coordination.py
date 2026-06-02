#!/usr/bin/env python3
"""Mark stale Wolfy Postgres agent tasks/runs as blocked.

Silent unless it changes rows. This prevents orphaned in_progress/started rows
from failed cron or diagnostic runs from clogging coordination.
"""
from __future__ import annotations

import sys

import psycopg

DSN = 'dbname=wolfy user=root host=/var/run/postgresql'
TASK_TIMEOUT = "3 hours"
RUN_TIMEOUT = "3 hours"


def main() -> int:
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_tasks
            SET status='blocked', updated_at=now(),
                description=concat_ws(E'\n', description, %s::text)
            WHERE status='in_progress'
              AND claimed_at < now() - %s::interval
            RETURNING id, agent_name, task_type, title
            """,
            (f'Blocked: stale in_progress task exceeded {TASK_TIMEOUT}; investigate prior run before retrying.', TASK_TIMEOUT),
        )
        tasks = cur.fetchall()
        cur.execute(
            """
            UPDATE agent_runs
            SET status='blocked', ended_at=now(),
                error_message=COALESCE(error_message, %s),
                summary=COALESCE(summary, %s)
            WHERE status='started'
              AND started_at < now() - %s::interval
            RETURNING id, agent_name, role, job_id
            """,
            (f'stale started run exceeded {RUN_TIMEOUT}', f'Stale run exceeded {RUN_TIMEOUT}; blocked by watchdog.', RUN_TIMEOUT),
        )
        runs = cur.fetchall()
        # Be explicit: no-agent cron wrappers invoke this through subprocesses,
        # and stale rows must remain blocked after the process exits.
        conn.commit()
    if tasks or runs:
        print('Wolfy Postgres stale coordination cleanup:')
        for row in tasks:
            print(f'- blocked task id={row[0]} agent={row[1]} type={row[2]} title={row[3]}')
        for row in runs:
            print(f'- blocked run id={row[0]} agent={row[1]} role={row[2]} job={row[3]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
