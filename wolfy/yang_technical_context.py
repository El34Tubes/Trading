#!/usr/bin/env python3
"""Print Postgres-first context for Yang, Wolfy's technical entry/exit agent."""
from __future__ import annotations

import os
import sys
from pathlib import Path

WOLFY_DIR = Path('/root/.hermes/wolfy')
if str(WOLFY_DIR) not in sys.path:
    sys.path.insert(0, str(WOLFY_DIR))

from budget_wake_gate import budget_wake_gate

try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None

from wolfy_agent_coordination import claim_next_task, connect, ensure_agent_task, finish_agent_run, stable_fingerprint, start_agent_run
from eod_governance import print_eod_governance

PG_DSN = 'dbname=wolfy user=root host=/var/run/postgresql'
CLI = '/root/.hermes/wolfy/wolfy_agent_cli.py'


def _pg_fetch_dicts(cur, sql: str, params: tuple = ()) -> list[dict]:
    cur.execute(sql, params)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def ensure_pg_yang_reviews(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS yang_reviews (
          id BIGSERIAL PRIMARY KEY,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          recommendation_id TEXT,
          alpha_lead_id TEXT,
          ticker TEXT NOT NULL,
          wolfy_alpha_thesis TEXT NOT NULL,
          technical_status TEXT NOT NULL,
          entry_trigger TEXT,
          entry_zone TEXT,
          stop_invalidation TEXT,
          target_exit_plan TEXT,
          atr TEXT,
          r_multiple TEXT,
          trend_read TEXT,
          relative_strength_read TEXT,
          volume_read TEXT,
          notes TEXT,
          raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb
        )
    """)
    cur.execute('CREATE INDEX IF NOT EXISTS idx_pg_yang_reviews_rec_created ON yang_reviews(recommendation_id, created_at DESC)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_pg_yang_reviews_ticker_created ON yang_reviews(ticker, created_at DESC)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_pg_yang_reviews_status ON yang_reviews(technical_status, created_at DESC)')


def start_yang_run(candidates: list[dict]) -> tuple[int, int | None]:
    with connect(PG_DSN) as conn:
        if not candidates:
            run_id = start_agent_run(conn, agent_name='Yang', role='technical_entry_exit', job_id='yang-post-sentinel', status='completed', summary='No Yang-eligible Postgres Wolfy recommendations.')
            finish_agent_run(conn, run_id, status='completed', summary='No Yang-eligible Postgres Wolfy recommendations.', records_created=0)
            return run_id, None
        fingerprint = stable_fingerprint('yang-technical-postgres', [(c['recommendation_id'], c['ticker'], c['status'], c.get('alpha_lead_id')) for c in candidates])
        ensured = ensure_agent_task(conn, agent_name='Yang', task_type='technical_entry_exit', title=f'Yang technical plan for {len(candidates)} Postgres Wolfy candidate(s)', description='Build technical entry/exit plan only after Wolfy alpha thesis/recommendation exists in Postgres. Do not originate alpha or approve trades.', source_fingerprint=fingerprint, topic_tags=['yang', 'technical', 'entry-exit', 'postgres-primary'], ticker_symbols=[c['ticker'] for c in candidates], priority=10)
        claim = claim_next_task(conn, agent_name='Yang', task_type='technical_entry_exit', source_fingerprint=fingerprint)
        if claim is None:
            if ensured.status == 'completed':
                summary = f'Yang task already completed; no duplicate technical-analysis work needed. task_id={ensured.id}'
                run_id = start_agent_run(conn, agent_name='Yang', role='technical_entry_exit', job_id='yang-post-sentinel', task_id=ensured.id, status='completed', summary=summary)
                finish_agent_run(conn, run_id, status='completed', summary=summary, records_created=0)
                return run_id, None
            run_id = start_agent_run(conn, agent_name='Yang', role='technical_entry_exit', job_id='yang-post-sentinel', task_id=ensured.id, status='blocked', summary=f'Duplicate/already claimed Yang task; status={ensured.status}.')
            finish_agent_run(conn, run_id, status='blocked', summary=f'Duplicate/already claimed Yang task; status={ensured.status}.', error_message='duplicate-or-already-claimed')
            return run_id, None
        run_id = start_agent_run(conn, agent_name='Yang', role='technical_entry_exit', job_id='yang-post-sentinel', task_id=claim.id, status='started', summary=f'Yang claimed {len(candidates)} Postgres alpha candidate(s).')
        return run_id, claim.id


def main() -> None:
    if not budget_wake_gate(label='Yang'):
        return
    print('Yang technical-analysis context')
    if psycopg is None:
        print('Postgres primary unavailable: psycopg import failed. Yang must block; do not fall back to SQLite for live technical context.')
        return
    with psycopg.connect(PG_DSN) as pg, pg.cursor() as cur:
        ensure_pg_yang_reviews(cur)
        pg.commit()
        candidates = _pg_fetch_dicts(cur, """
            SELECT r.id AS recommendation_id, r.ticker, r.status, r.action, r.recommendation_type,
                   r.confidence, r.thesis AS wolfy_alpha_thesis, r.setup_type, r.entry_zone,
                   r.entry_trigger, r.stop, r.target, r.risk_reward, r.notes,
                   l.id AS alpha_lead_id, l.title AS alpha_lead_title, l.thesis AS alpha_lead_thesis,
                   l.evidence_quality_score AS alpha_evidence_quality_score
            FROM recommendations r
            LEFT JOIN LATERAL (
                SELECT * FROM alpha_leads l2
                WHERE l2.ticker=r.ticker
                ORDER BY l2.updated_at DESC, l2.id DESC
                LIMIT 1
            ) l ON true
            WHERE lower(r.status) IN ('approved','pending_review','needs_yang','alpha_candidate','watching','candidate')
              AND trim(COALESCE(r.thesis,'')) <> ''
            ORDER BY r.created_at DESC, r.id DESC
            LIMIT 12
        """)
        ineligible = _pg_fetch_dicts(cur, """
            SELECT id, ticker, status, action, recommendation_type, thesis, notes
            FROM recommendations
            WHERE lower(status) IN ('approved','pending_review','needs_yang','alpha_candidate','watching','candidate')
              AND trim(COALESCE(thesis,'')) = ''
            ORDER BY created_at DESC, id DESC
            LIMIT 8
        """)
        scanner = _pg_fetch_dicts(cur, """
            SELECT sr.* FROM scanner_results sr
            JOIN (SELECT max(id) AS run_id FROM scanner_runs) latest ON latest.run_id=sr.run_id
            ORDER BY sr.score DESC LIMIT 15
        """)
        rules = _pg_fetch_dicts(cur, """
            SELECT rule_name, description FROM strategy_rules
            WHERE enabled=true AND (rule_type IN ('technical','risk','portfolio') OR rule_type IS NULL)
            ORDER BY id DESC LIMIT 12
        """)
        counts = {}
        for t in ['recommendations','yang_reviews','alpha_leads','paper_trades','scanner_runs','scanner_results','strategy_rules']:
            try:
                cur.execute(f'SELECT COUNT(*) FROM {t}')
                counts[t] = int(cur.fetchone()[0])
            except Exception:
                pg.rollback(); counts[t] = 0
    smoke_mode = os.environ.get('WOLFY_CONTEXT_SMOKE') == '1'
    if smoke_mode:
        run_id, task_id = None, None
    else:
        run_id, task_id = start_yang_run(candidates)
    print(f'Postgres DB=wolfy DSN={PG_DSN}')
    print('SQLite fallback: disabled for live Yang context; remaining SQLite consumers are compatibility only.')
    print_eod_governance()
    print('Postgres counts: ' + ', '.join(f'{k}={v}' for k, v in counts.items()))
    if smoke_mode:
        print('Postgres agent run: SMOKE_MODE=true no agent_runs row opened and no agent_task claimed')
    else:
        print(f'Postgres agent run: AGENT_RUN_ID={run_id}')
    if task_id:
        print(f'Postgres agent task claim: CLAIMED=true AGENT_TASK_ID={task_id}')
        print('Persistence target: Postgres table yang_reviews. Insert only when EOD technical evidence is sufficient; raw_payload should include FACT/JUDGMENT separation and source rows used.')
        print(f'After DB/status writes, run: python3 {CLI} complete --task-id {task_id} --run-id {run_id} --records-created <N> --summary "<Yang technical plan summary>"')
        print(f'If blocked, run: python3 {CLI} block --task-id {task_id} --run-id {run_id} --reason "<specific blocker>"')
    elif candidates:
        print('Postgres agent task claim: CLAIMED=false. Existing Yang task is already completed or currently claimed; do not spend duplicate Yang work.')
    else:
        print('Postgres agent run completed automatically because there are no Yang-eligible Wolfy alpha recommendations.')
    print('Role: Yang owns technical analysis for entry/exit after Wolfy identifies alpha candidates. Yang does not originate alpha theses and does not approve trades; Sentinel handles feasibility/risk approval.')
    print('Hard gate: only build/persist entry/exit/invalidation/ATR/R-multiple plans for recommendations with a non-empty Wolfy alpha thesis. Scanner rows are context only, not trade theses.')
    print('Required Yang output: EOD-only next-session technical plan separating FACT vs JUDGMENT: entry trigger/zone, invalidation/stop, target/exit plan, ATR/R multiple, trend/relative-strength/volume read, and wait-for-next-session-trigger/watch-only/no-trade. Do not label anything actionable intraday. Update Postgres yang_reviews only if enough EOD data is present; otherwise report no technical action.')
    if candidates:
        print('Yang-eligible Postgres Wolfy alpha recommendations:')
        for c in candidates:
            print(f"- recommendation_id={c['recommendation_id']} alpha_lead_id={c.get('alpha_lead_id')} ticker={c['ticker']} status={c['status']} action={c['action']} type={c['recommendation_type']} confidence={c['confidence']}")
            print(f"  wolfy_alpha_thesis={c['wolfy_alpha_thesis']}")
            if c.get('alpha_lead_thesis'):
                print(f"  linked_alpha_lead={c.get('alpha_lead_title')} thesis={c.get('alpha_lead_thesis')} evidence_quality={c.get('alpha_evidence_quality_score')}")
            print(f"  prior_plan setup={c['setup_type']} entry_zone={c['entry_zone']} trigger={c['entry_trigger']} stop={c['stop']} target={c['target']} rr={c['risk_reward']} notes={c['notes']}")
    else:
        print('Yang-eligible Postgres Wolfy alpha recommendations: none.')
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


if __name__ == '__main__':
    main()
