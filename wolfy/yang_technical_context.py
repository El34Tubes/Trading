#!/usr/bin/env python3
"""Print context for Yang, Wolfy's technical-analysis entry/exit agent, and start a Postgres run row."""
from __future__ import annotations

from pathlib import Path
import sqlite3

try:
    import psycopg
except Exception:
    psycopg = None

from wolfy_agent_coordination import claim_next_task, connect, ensure_agent_task, finish_agent_run, stable_fingerprint, start_agent_run
from yang_technical_reviews import eligible_yang_candidates, ensure_yang_review_tables

DB = Path('/root/.hermes/wolfy/wolfy.db')
PG_DSN = 'dbname=wolfy user=root host=/var/run/postgresql'
CLI = Path('/root/.hermes/wolfy/wolfy_agent_cli.py')


def start_yang_run(candidates: list[dict]) -> tuple[int, int | None]:
    with connect(PG_DSN) as conn:
        if not candidates:
            run_id = start_agent_run(conn, agent_name='Yang', role='technical_entry_exit', job_id='yang-post-sentinel', status='completed', summary='No Yang-eligible Wolfy alpha recommendations.')
            finish_agent_run(conn, run_id, status='completed', summary='No Yang-eligible Wolfy alpha recommendations.', records_created=0)
            return run_id, None
        fingerprint = stable_fingerprint('yang-technical', [(c['recommendation_id'], c['ticker'], c['status'], c.get('alpha_lead_id')) for c in candidates])
        ensured = ensure_agent_task(
            conn,
            agent_name='Yang',
            task_type='technical_entry_exit',
            title=f'Yang technical plan for {len(candidates)} Wolfy alpha candidate(s)',
            description='Build technical entry/exit plan only after Wolfy alpha thesis/recommendation exists. Do not originate alpha or approve trades.',
            source_fingerprint=fingerprint,
            topic_tags=['yang', 'technical', 'entry-exit'],
            ticker_symbols=[c['ticker'] for c in candidates],
            priority=10,
        )
        claim = claim_next_task(conn, agent_name='Yang', task_type='technical_entry_exit', source_fingerprint=fingerprint)
        if claim is None:
            run_id = start_agent_run(conn, agent_name='Yang', role='technical_entry_exit', job_id='yang-post-sentinel', task_id=ensured.id, status='blocked', summary=f'Duplicate/already claimed Yang task; status={ensured.status}.')
            finish_agent_run(conn, run_id, status='blocked', summary=f'Duplicate/already claimed Yang task; status={ensured.status}.', error_message='duplicate-or-already-claimed')
            return run_id, None
        run_id = start_agent_run(conn, agent_name='Yang', role='technical_entry_exit', job_id='yang-post-sentinel', task_id=claim.id, status='started', summary=f'Yang claimed {len(candidates)} Wolfy alpha candidate(s).')
        return run_id, claim.id


def main() -> None:
    ensure_yang_review_tables(DB)
    candidates = eligible_yang_candidates(DB, limit=12)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    ineligible = con.execute(
        """
        SELECT id, ticker, status, action, recommendation_type, thesis, notes
        FROM recommendations
        WHERE lower(status) IN ('approved','pending_review','needs_yang','alpha_candidate','watching','candidate')
          AND trim(COALESCE(thesis,'')) = ''
        ORDER BY timestamp DESC, id DESC
        LIMIT 8
        """
    ).fetchall()
    scanner = con.execute(
        """
        SELECT sr.* FROM scanner_results sr
        JOIN (SELECT max(id) AS run_id FROM scanner_runs) latest ON latest.run_id=sr.run_id
        ORDER BY sr.score DESC LIMIT 15
        """
    ).fetchall()
    rules = con.execute("SELECT rule_name, description FROM strategy_rules WHERE enabled=1 AND rule_type IN ('technical','risk','portfolio') ORDER BY id DESC LIMIT 12").fetchall()
    counts = {t: con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ['recommendations','yang_reviews','alpha_leads','paper_trades','scanner_runs','scanner_results','strategy_rules']}
    con.close()

    run_id, task_id = start_yang_run(candidates)

    print('Yang technical-analysis context')
    print(f'SQLite DB={DB}')
    print('Counts: ' + ', '.join(f'{k}={v}' for k, v in counts.items()))
    print(f'Postgres agent run: AGENT_RUN_ID={run_id}')
    if task_id:
        print(f'Postgres agent task claim: CLAIMED=true AGENT_TASK_ID={task_id}')
        print('Persistence helper: python3 /root/.hermes/wolfy/yang_technical_reviews.py persist --json-file <review_payload.json>')
        print('Each persisted review payload must include recommendation_id, ticker, wolfy_alpha_thesis, technical_status, entry_trigger, stop_invalidation, target_exit_plan, ATR, and R multiple when available.')
        print(f'After DB/status writes, run: python3 {CLI} complete --task-id {task_id} --run-id {run_id} --records-created <N> --summary "<Yang technical plan summary>"')
        print(f'If blocked, run: python3 {CLI} block --task-id {task_id} --run-id {run_id} --reason "<specific blocker>"')
    elif candidates:
        print('Postgres agent task claim: CLAIMED=false. Do not spend duplicate Yang work; report blocked duplicate briefly.')
    else:
        print('Postgres agent run completed automatically because there are no Yang-eligible Wolfy alpha recommendations.')
    print('Role: Yang owns technical analysis for entry/exit after Wolfy identifies alpha candidates. Yang does not originate fundamental alpha theses and does not approve trades; Sentinel handles feasibility/risk approval.')
    print('Hard gate: only build/persist entry/exit/invalidation/ATR/R-multiple plans for recommendations with a non-empty Wolfy alpha thesis. Scanner rows are context only, not trade theses.')
    print('Required Yang output: entry trigger/zone, invalidation/stop, target/exit plan, ATR/R multiple, trend/relative-strength/volume read, and actionable-now/wait/no-trade. Update yang_reviews only if enough data is present; otherwise report no technical action.')
    if candidates:
        print('Yang-eligible Wolfy alpha recommendations:')
        for c in candidates:
            print(f"- recommendation_id={c['recommendation_id']} alpha_lead_id={c.get('alpha_lead_id')} ticker={c['ticker']} status={c['status']} action={c['action']} type={c['recommendation_type']} confidence={c['confidence']}")
            print(f"  wolfy_alpha_thesis={c['wolfy_alpha_thesis']}")
            if c.get('alpha_lead_thesis'):
                print(f"  linked_alpha_lead={c.get('alpha_lead_title')} thesis={c.get('alpha_lead_thesis')} evidence_quality={c.get('alpha_evidence_quality_score')}")
            print(f"  prior_plan setup={c['setup_type']} entry_zone={c['entry_zone']} trigger={c['entry_trigger']} stop={c['stop']} target={c['target']} rr={c['risk_reward']} notes={c['notes']}")
    else:
        print('Yang-eligible Wolfy alpha recommendations: none.')
    if ineligible:
        print('Recommendations deliberately skipped because no Wolfy alpha thesis exists:')
        for r in ineligible:
            print(f"- id={r['id']} ticker={r['ticker']} status={r['status']} action={r['action']} type={r['recommendation_type']}")
    print('Latest scanner technical context:')
    for s in scanner:
        print(f"- {s['ticker']}: score={s['score']} close={s['close']} r5={s['r5']} r20={s['r20']} r60={s['r60']} vs20={s['vs20']} vs50={s['vs50']} atr={s['atr']} avg_vol={s['avg_volume']} high20={s['high20']} low20={s['low20']} liq={s['liquidity_pass']}")
    print('Relevant technical/risk rules:')
    for r in rules:
        print(f"- {r['rule_name']}: {r['description']}")
    if psycopg is not None:
        try:
            with psycopg.connect(PG_DSN) as pg, pg.cursor() as cur:
                cur.execute("SELECT status, count(*) FROM agent_runs WHERE agent_name='Yang' GROUP BY status ORDER BY status")
                rows = cur.fetchall()
                if rows:
                    print('Postgres Yang agent_runs: ' + ', '.join(f'{s}={c}' for s, c in rows))
        except Exception as e:
            print(f'Postgres run table unavailable: {type(e).__name__}: {e}')


if __name__ == '__main__':
    main()
