#!/usr/bin/env python3
"""Print compact context for a Jonah knowledge-build cron run.

SQLite remains the live source of truth during transition. Postgres is now an
active oversight layer: Jonah must create/dedupe/claim an agent_tasks row before
spending LLM tokens, and every run gets an agent_runs ledger row.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import sqlite3
import subprocess

try:
    import psycopg
except Exception:  # pragma: no cover - script should degrade gracefully
    psycopg = None

try:
    from wolfy_agent_coordination import (
        claim_next_task,
        connect,
        ensure_agent_task,
        finish_agent_run,
        stable_fingerprint,
        start_agent_run,
    )
except Exception:  # pragma: no cover - context should still print if helper import fails
    claim_next_task = connect = ensure_agent_task = finish_agent_run = stable_fingerprint = start_agent_run = None

from eod_governance import print_eod_governance

DB = Path('/root/.hermes/wolfy/wolfy.db')
SYNC = Path('/root/.hermes/wolfy/sync_sqlite_to_postgres.py')
CLI = Path('/root/.hermes/wolfy/wolfy_agent_cli.py')
PG_DSN = 'dbname=wolfy user=root host=/var/run/postgresql'
BUDGET_GATE = Path('/root/.hermes/wolfy/guardian/budget_gate.py')


def budget_wake_gate() -> bool:
    """Return False after emitting a cron wakeAgent=false gate when budget blocks."""
    if os.environ.get('WOLFY_SKIP_BUDGET_GATE') == '1':
        return True
    if not BUDGET_GATE.exists():
        print('Budget gate: missing; Jonah blocked, do not spend research tokens.')
        print('{"wakeAgent": false, "reason": "budget_gate_missing"}')
        return False
    try:
        proc = subprocess.run(
            ['python3', str(BUDGET_GATE), '--no-record'],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
            check=False,
        )
    except Exception as exc:
        print(f'Budget gate: error {type(exc).__name__}: {exc}; Jonah blocked, do not spend research tokens.')
        print('{"wakeAgent": false, "reason": "budget_gate_error"}')
        return False
    gate_output = ' '.join((proc.stdout or '').split())
    if proc.returncode == 0 and gate_output.startswith('BUDGET=ok'):
        print(f'Budget gate: {gate_output}')
        return True
    reason = gate_output or f'exit={proc.returncode}'
    print(f'skipped: budget {reason}')
    print('{"wakeAgent": false, "reason": "budget"}')
    return False


def maybe_sync_postgres() -> str:
    if not SYNC.exists():
        return 'Postgres sync: unavailable; sync script missing.'
    try:
        out = subprocess.check_output(['python3', str(SYNC)], text=True, stderr=subprocess.STDOUT, timeout=45).strip()
        return f'Postgres sync: {out}'
    except Exception as e:
        return f'Postgres sync: failed ({type(e).__name__}: {e})'


def postgres_context(topic_hint: str | None) -> list[str]:
    lines: list[str] = []
    if psycopg is None:
        return ['Postgres oversight: psycopg unavailable; using SQLite-only context.']
    try:
        with psycopg.connect(PG_DSN) as conn, conn.cursor() as cur:
            cur.execute("SELECT artifact_type, count(*) FROM agent_artifacts GROUP BY artifact_type ORDER BY artifact_type")
            counts = cur.fetchall()
            if counts:
                lines.append('Postgres artifacts: ' + ', '.join(f'{k}={v}' for k, v in counts))
            cur.execute("SELECT count(*) FROM knowledge_chunks")
            lines.append(f'Postgres knowledge_chunks={cur.fetchone()[0]}')
            cur.execute("SELECT count(*) FROM knowledge_chunks WHERE embedding IS NOT NULL")
            lines.append(f'Postgres embedded_chunks={cur.fetchone()[0]}')
            cur.execute("SELECT status, count(*) FROM agent_tasks GROUP BY status ORDER BY status")
            task_counts = cur.fetchall()
            if task_counts:
                lines.append('Postgres agent_tasks: ' + ', '.join(f'{k}={v}' for k, v in task_counts))
            cur.execute("SELECT status, count(*) FROM agent_runs GROUP BY status ORDER BY status")
            run_counts = cur.fetchall()
            if run_counts:
                lines.append('Postgres agent_runs: ' + ', '.join(f'{k}={v}' for k, v in run_counts))
            if topic_hint:
                cur.execute(
                    """
                    SELECT artifact_type, title, left(body, 220) AS snippet, updated_at
                    FROM agent_artifacts
                    WHERE body ILIKE %s OR title ILIKE %s
                    ORDER BY updated_at DESC
                    LIMIT 5
                    """,
                    (f'%{topic_hint}%', f'%{topic_hint}%'),
                )
                rows = cur.fetchall()
                if rows:
                    lines.append('Prior related artifacts Jonah should avoid duplicating:')
                    for artifact_type, title, snippet, updated_at in rows:
                        clean = ' '.join((snippet or '').split())
                        lines.append(f'- {artifact_type}: {title} ({updated_at}) :: {clean}')
                else:
                    lines.append(f'Prior related artifacts for hint "{topic_hint}": none found.')
    except Exception as e:
        lines.append(f'Postgres oversight: unavailable ({type(e).__name__}: {e})')
    return lines


def build_task_fingerprint(task: sqlite3.Row | None, source: sqlite3.Row | None) -> str:
    assert stable_fingerprint is not None
    return stable_fingerprint(
        'jonah-research-context',
        'training_task', task['id'] if task else '', task['task_name'] if task else '', task['objective'] if task else '',
        'knowledge_source', source['id'] if source else '', source['title'] if source else '', source['url_or_reference'] if source else '',
    )


def claim_postgres_task(task: sqlite3.Row | None, source: sqlite3.Row | None) -> tuple[list[str], int | None, int | None, str | None]:
    """Ensure+claim Jonah's next research task before any LLM work starts."""
    if connect is None or ensure_agent_task is None or claim_next_task is None or start_agent_run is None:
        return (['Postgres agent task claim: helper unavailable; Jonah should treat this run as blocked until helper import is fixed.'], None, None, None)
    if not task and not source:
        with connect(PG_DSN) as conn:
            run_id = start_agent_run(conn, agent_name='Jonah', role='research', job_id='jonah-15min', status='completed', summary='No queued SQLite training/source task.')
            finish_agent_run(conn, run_id, status='completed', summary='No queued SQLite training/source task.', records_created=0)
        return ([f'Postgres agent run: AGENT_RUN_ID={run_id} status=completed no queued Jonah task.'], None, run_id, None)

    fingerprint = build_task_fingerprint(task, source)
    task_title = task['task_name'] if task else f"Research source: {source['title']}"
    source_title = source['title'] if source else 'none'
    description = (
        f"Jonah durable research build. SQLite training_task_id={task['id'] if task else 'none'}; "
        f"knowledge_source_id={source['id'] if source else 'none'}; source={source_title}. "
        "Claim before token spend; write knowledge_notes/strategy_rules; complete or block after DB writes."
    )
    priority = int(task['priority'] if task else source['priority'])
    topic_tags = ['jonah', 'research']
    if task:
        topic_tags.append(str(task['category']))
    with connect(PG_DSN) as conn:
        ensured = ensure_agent_task(
            conn,
            agent_name='Jonah',
            task_type='research',
            title=task_title,
            description=description,
            source_fingerprint=fingerprint,
            topic_tags=topic_tags,
            priority=priority,
        )
        claim = claim_next_task(conn, agent_name='Jonah', task_type='research', source_fingerprint=fingerprint)
        if claim is None:
            run_id = start_agent_run(conn, agent_name='Jonah', role='research', job_id='jonah-15min', task_id=ensured.id, status='blocked', summary=f'No claim available; task status={ensured.status}')
            finish_agent_run(conn, run_id, status='blocked', summary=f'No claim available; task status={ensured.status}', error_message='duplicate-or-already-claimed')
            return ([
                'Postgres agent task claim: CLAIMED=false',
                f'AGENT_TASK_ID={ensured.id} TASK_STATUS={ensured.status} SOURCE_FINGERPRINT={fingerprint}',
                f'AGENT_RUN_ID={run_id} STATUS=blocked',
                'Instruction: do not spend research tokens on this duplicate/already-claimed Jonah task; report the blocked duplicate briefly.',
            ], None, run_id, fingerprint)
        run_id = start_agent_run(conn, agent_name='Jonah', role='research', job_id='jonah-15min', task_id=claim.id, status='started', summary='Jonah research task claimed before token spend.')
    return ([
        'Postgres agent task claim: CLAIMED=true',
        f'AGENT_TASK_ID={claim.id} CLAIM_TOKEN={claim.claim_token} SOURCE_FINGERPRINT={fingerprint}',
        f'AGENT_RUN_ID={run_id}',
        f'After successful SQLite writes, run: python3 {CLI} complete --task-id {claim.id} --run-id {run_id} --records-created <N> --summary "<what Jonah inserted>"',
        f'If blocked, run: python3 {CLI} block --task-id {claim.id} --run-id {run_id} --reason "<specific blocker>"',
    ], claim.id, run_id, fingerprint)


def main() -> None:
    """Postgres-only Jonah context. SQLite is retired for live knowledge runs."""
    if not budget_wake_gate():
        return
    print('Jonah knowledge-build context')
    print('Wolfy DB=Postgres primary; SQLite retired for live Jonah context')
    print_eod_governance()
    for line in postgres_context(None):
        print(line)
    if os.environ.get('WOLFY_CONTEXT_SMOKE') == '1':
        print('Postgres agent task claim: SMOKE=true; no task claimed and no agent_run opened.')
        print('Instruction: smoke verification only; live Jonah cron may claim queued tasks normally.')
        return
    if connect is None or claim_next_task is None or start_agent_run is None:
        print('Postgres agent task claim: helper unavailable; Jonah blocked, do not spend research tokens.')
        return
    with connect(PG_DSN) as conn:
        claim = claim_next_task(conn, agent_name='Jonah', task_type='scanner_alpha_research')
        if claim is None:
            claim = claim_next_task(conn, agent_name='Jonah', task_type='research')
        if claim is None:
            run_id = start_agent_run(conn, agent_name='Jonah', role='research', job_id='jonah-20min', status='completed', summary='No queued Postgres Jonah task.')
            finish_agent_run(conn, run_id, status='completed', summary='No queued Postgres Jonah task.', records_created=0)
            print(f'Postgres agent run: AGENT_RUN_ID={run_id} status=completed no queued Jonah task.')
            print('Instruction: stay quiet/minimal; no filler research when there is no claimed task.')
            return
        run_id = start_agent_run(conn, agent_name='Jonah', role='research', job_id='jonah-20min', task_id=claim.id, status='started', summary='Jonah Postgres task claimed before token spend.')
    print('Postgres agent task claim: CLAIMED=true')
    print(f'AGENT_TASK_ID={claim.id} CLAIM_TOKEN={claim.claim_token} SOURCE_FINGERPRINT={claim.source_fingerprint}')
    print(f'AGENT_RUN_ID={run_id}')
    print(f'Task: title={claim.title} type={claim.task_type}')
    print('Instruction: write durable concise research to Postgres agent_artifacts/knowledge_chunks or complete/block the task; do not write SQLite.')
    print(f'After successful Postgres writes, run: python3 {CLI} complete --task-id {claim.id} --run-id {run_id} --records-created <N> --summary "<what Jonah inserted>"')
    print(f'If blocked, run: python3 {CLI} block --task-id {claim.id} --run-id {run_id} --reason "<specific blocker>"')


if __name__ == '__main__':
    main()
