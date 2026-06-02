#!/usr/bin/env python3
"""Print compact context for a Jonah knowledge-build cron run.

SQLite remains the live source of truth during transition. Postgres is now an
active oversight layer: Jonah must create/dedupe/claim an agent_tasks row before
spending LLM tokens, and every run gets an agent_runs ledger row.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
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
    if not DB.exists():
        print('Wolfy DB not initialized. Run /root/.hermes/wolfy/init_wolfy_db.py first.')
        return

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()
    # Only queue fresh work here. Re-selecting stale SQLite ``in_progress`` rows
    # creates a deduped/blocked Postgres task every Jonah cron tick after the
    # original claim has already completed or blocked. Stale in-progress cleanup
    # is owned by the coordination watchdog, not by the context generator.
    task = con.execute(
        "SELECT * FROM training_tasks WHERE status = 'queued' "
        "ORDER BY priority ASC, COALESCE(last_attempt_at,'') ASC, id ASC LIMIT 1"
    ).fetchone()
    source = con.execute(
        "SELECT * FROM knowledge_sources WHERE status = 'queued' "
        "ORDER BY priority ASC, id ASC LIMIT 1"
    ).fetchone()
    counts = {t: con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in [
        'knowledge_sources', 'knowledge_notes', 'strategy_rules', 'training_tasks',
        'recommendations', 'paper_trades', 'scanner_runs', 'system_metrics'
    ]}

    topic_hint = None
    if task:
        topic_hint = str(task['task_name']).split()[0]
    elif source:
        topic_hint = str(source['title']).split()[0]

    print('Jonah 15-minute knowledge-build context')
    print(f'SQLite DB={DB}')
    print_eod_governance()
    print('SQLite counts: ' + ', '.join(f'{k}={v}' for k, v in counts.items()))
    print(maybe_sync_postgres())

    claim_lines, claimed_task_id, run_id, _fingerprint = claim_postgres_task(task, source)
    for line in claim_lines:
        print(line)

    if claimed_task_id is not None:
        if task:
            con.execute("UPDATE training_tasks SET status='in_progress', last_attempt_at=? WHERE id=?", (now, task['id']))
        if source:
            con.execute("UPDATE knowledge_sources SET status='in_progress', updated_at=? WHERE id=?", (now, source['id']))
        con.commit()
    con.close()

    for line in postgres_context(topic_hint):
        print(line)
    if task:
        print(f"Next training task: id={task['id']} category={task['category']} name={task['task_name']} objective={task['objective']}")
    else:
        print('No queued training task found; create/refine strategy rules or grade recommendations.')
    if source:
        print(f"Next source/framework: id={source['id']} title={source['title']} author={source['author']} type={source['source_type']} ref={source['url_or_reference']}")
        ref = source['url_or_reference'] or ''
        if ref.startswith('/') and Path(ref).exists():
            print(f'Instruction: this source is a user-provided local file. Read it directly before distilling knowledge: {ref}')
        else:
            print('Instruction: use public/legal summaries/interviews/course pages unless user has provided source text. Do not claim to have read a copyrighted book unless actual text/notes were provided.')
    else:
        print('No queued source found; add more public or user-provided materials. File inbox: /root/.hermes/wolfy/sources/inbox/; queue with python3 /root/.hermes/wolfy/queue_knowledge_source_files.py')
    if claimed_task_id is None and (task or source):
        print('Required output: no research spend this run; report blocked duplicate/already-claimed task and do not insert filler research.')
    else:
        print('Before writing: check prior artifacts above to avoid duplicate work. Required DB writes after reasoning: insert knowledge_notes and/or strategy_rules; update source/task status; optionally write a concise progress report to reports. Do not recommend trades, do not create numeric edge by LLM inference, and tag EOD-only/FACT-vs-JUDGMENT implications where relevant. Finish the Postgres agent_runs/agent_tasks rows with the command printed above.')


if __name__ == '__main__':
    main()
