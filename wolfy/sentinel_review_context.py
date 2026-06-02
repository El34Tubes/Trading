#!/usr/bin/env python3
"""Print Sentinel context for reviewing Wolfy pending recommendations."""
from __future__ import annotations

import sqlite3
from pathlib import Path

try:
    import psycopg
except Exception:
    psycopg = None

try:
    from wolfy_agent_coordination import claim_next_task, connect, ensure_agent_task, finish_agent_run, stable_fingerprint, start_agent_run
except Exception:
    claim_next_task = connect = ensure_agent_task = finish_agent_run = stable_fingerprint = start_agent_run = None

from eod_governance import print_eod_governance

SQLITE_DB = Path('/root/.hermes/wolfy/wolfy.db')
PG_DSN = 'dbname=wolfy user=root host=/var/run/postgresql'
CLI = Path('/root/.hermes/wolfy/wolfy_agent_cli.py')


def start_sentinel_run(recs: list[sqlite3.Row]) -> tuple[int | None, int | None]:
    reviewable_count = len(recs)
    if connect is None or start_agent_run is None:
        print('Postgres agent run: helper unavailable; Sentinel should report this blocker.')
        return None, None
    task_id = None
    fingerprint = None
    with connect(PG_DSN) as conn:
        if reviewable_count and ensure_agent_task is not None and claim_next_task is not None and stable_fingerprint is not None:
            fingerprint = stable_fingerprint('sentinel-review', [(r['id'], r['ticker'], r['status']) for r in recs])
            ensured = ensure_agent_task(
                conn,
                agent_name='Sentinel',
                task_type='recommendation_review',
                title=f'Review {reviewable_count} pending Wolfy recommendation(s)',
                description='Sentinel post-Wolfy review task. Claim before token spend; write recommendation_reviews and update SQLite recommendation statuses.',
                source_fingerprint=fingerprint,
                topic_tags=['sentinel', 'risk-review'],
                priority=10,
            )
            claim = claim_next_task(conn, agent_name='Sentinel', task_type='recommendation_review', source_fingerprint=fingerprint)
            if claim is None:
                run_id = start_agent_run(
                    conn,
                    agent_name='Sentinel',
                    role='risk_reviewer',
                    job_id='sentinel-post-wolfy',
                    task_id=ensured.id,
                    status='blocked',
                    summary=f'Duplicate/already claimed Sentinel review task; task status={ensured.status}.',
                )
                if finish_agent_run is not None:
                    finish_agent_run(conn, run_id, status='blocked', summary=f'Duplicate/already claimed Sentinel review task; task status={ensured.status}.', error_message='duplicate-or-already-claimed')
                print('Postgres agent task claim: CLAIMED=false')
                print(f'AGENT_TASK_ID={ensured.id} TASK_STATUS={ensured.status} SOURCE_FINGERPRINT={fingerprint}')
                print(f'AGENT_RUN_ID={run_id} STATUS=blocked')
                print('Instruction: do not spend review tokens on this duplicate/already-claimed Sentinel task; report the blocked duplicate briefly.')
                return run_id, None
            task_id = claim.id
            print('Postgres agent task claim: CLAIMED=true')
            print(f'AGENT_TASK_ID={task_id} CLAIM_TOKEN={claim.claim_token} SOURCE_FINGERPRINT={fingerprint}')

        run_id = start_agent_run(
            conn,
            agent_name='Sentinel',
            role='risk_reviewer',
            job_id='sentinel-post-wolfy',
            task_id=task_id,
            status='started',
            summary=f'Sentinel review context loaded with {reviewable_count} reviewable recommendation(s).',
        )
        if reviewable_count == 0 and finish_agent_run is not None:
            finish_agent_run(conn, run_id, status='completed', summary='No pending recommendations to review.', records_created=0)
    print(f'Postgres agent run: AGENT_RUN_ID={run_id}')
    if reviewable_count and task_id:
        print(f'Run deterministic review persistence: python3 /root/.hermes/wolfy/sentinel_reviews.py --db {SQLITE_DB}')
        print(f'After script writes recommendation_reviews, run: python3 {CLI} complete --task-id {task_id} --run-id {run_id} --records-created <N> --summary "<Sentinel decisions>"')
        print(f'If blocked, run: python3 {CLI} block --task-id {task_id} --run-id {run_id} --reason "<specific blocker>"')
    elif reviewable_count:
        print(f'If proceeding without a task claim, finish run with: python3 {CLI} run-finish --run-id {run_id} --status blocked --error-message "task claim failed" --summary "task claim failed"')
    else:
        print('Postgres agent run completed automatically because there are no pending recommendations.')
    return run_id, task_id


def main() -> None:
    con = sqlite3.connect(SQLITE_DB)
    con.row_factory = sqlite3.Row
    recs = con.execute(
        """
        SELECT * FROM recommendations
        WHERE lower(status) IN ('pending_review','pending sentinel review','watching','candidate')
        ORDER BY timestamp DESC, id DESC
        LIMIT 10
        """
    ).fetchall()
    rules = con.execute(
        "SELECT rule_name, rule_type, description FROM strategy_rules WHERE enabled=1 ORDER BY id DESC LIMIT 15"
    ).fetchall()
    counts = {t: con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ['recommendations','paper_trades','recommendation_outcomes','strategy_rules','knowledge_notes']}
    con.close()

    print('Sentinel recommendation-review context')
    print(f'SQLite DB={SQLITE_DB}')
    print_eod_governance()
    print('Counts: ' + ', '.join(f'{k}={v}' for k, v in counts.items()))
    print('User hard constraints: Robinhood-tradable only; no shorts; options allowed but prefer defined risk; max 3 concurrent positions; $5,000 paper account; avoid PDT violations; stops required; avoid foreign manipulation/government-interference risk.')
    start_sentinel_run(recs)
    if not recs:
        print('Pending recommendations: none. Sentinel should stay terse and report no reviewable recommendations.')
    else:
        print('Pending/reviewable recommendations:')
        for r in recs:
            print(f"- id={r['id']} ticker={r['ticker']} action={r['action']} type={r['recommendation_type']} status={r['status']} confidence={r['confidence']}")
            print(f"  thesis={r['thesis']}")
            print(f"  setup={r['setup_type']} entry={r['entry_zone']} trigger={r['entry_trigger']} stop={r['stop']} target={r['target']} rr={r['risk_reward']} size={r['position_size_suggestion']} hold={r['holding_period']}")
            print(f"  notes={r['notes']}")
    print('Active strategy/risk rules:')
    for r in rules:
        print(f"- {r['rule_name']} [{r['rule_type']}]: {r['description']}")

    if psycopg is not None:
        try:
            with psycopg.connect(PG_DSN) as pg, pg.cursor() as cur:
                cur.execute("SELECT count(*) FROM recommendation_reviews")
                print(f'Postgres recommendation_reviews={cur.fetchone()[0]}')
                cur.execute("SELECT status, count(*) FROM agent_runs WHERE agent_name='Sentinel' GROUP BY status ORDER BY status")
                rows = cur.fetchall()
                if rows:
                    print('Postgres Sentinel agent_runs: ' + ', '.join(f'{status}={count}' for status, count in rows))
        except Exception as e:
            print(f'Postgres review/run table unavailable: {type(e).__name__}: {e}')

    print('Required output: run sentinel_reviews.py for deterministic review persistence. For each reviewable recommendation it writes Postgres recommendation_reviews and updates SQLite recommendations.status to approved, rejected, or needs_revision. Reject/needs_revision any recommendation that is not EOD closing-data backed, lacks deterministic signal/setup support, blurs FACT vs JUDGMENT, or implies intraday/auto-execution. LLM rationale may be added in reports, but mechanical checks must not be bypassed. If no pending recommendations exist, do not invent any.')


if __name__ == '__main__':
    main()
