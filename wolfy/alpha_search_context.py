#!/usr/bin/env python3
"""Print Postgres-only context for the standalone Wolfy Alpha Search Report."""
from __future__ import annotations

from pathlib import Path
import os

import psycopg

from wolfy_agent_coordination import connect, start_agent_run
from alpha_search_pipeline import status_snapshot
from eod_governance import print_eod_governance

PG_DSN = 'dbname=wolfy user=root host=/var/run/postgresql'
CLI = Path('/root/.hermes/wolfy/wolfy_agent_cli.py')
ALPHA_PIPELINE = Path('/root/.hermes/wolfy/alpha_search_pipeline.py')


def fetch_dicts(cur, sql: str, params: tuple = ()) -> list[dict]:
    cur.execute(sql, params)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def main() -> None:
    with psycopg.connect(PG_DSN) as pg, pg.cursor() as cur:
        notes = fetch_dicts(cur, """
            SELECT title AS topic, left(body, 300) AS summary, array_to_string(topic_tags, ',') AS tags
            FROM agent_artifacts
            WHERE artifact_type IN ('knowledge_note','strategy_rule')
              AND (body ILIKE '%%alpha%%' OR body ILIKE '%%insider%%' OR body ILIKE '%%social%%' OR body ILIKE '%%suspicious%%')
            ORDER BY updated_at DESC LIMIT 12
        """)
        rules = fetch_dicts(cur, """
            SELECT title AS rule_name, artifact_type AS rule_type, left(body, 300) AS description
            FROM agent_artifacts
            WHERE artifact_type='strategy_rule'
              AND (title ILIKE '%%alpha%%' OR title ILIKE '%%insider%%' OR title ILIKE '%%social%%' OR title ILIKE '%%yang%%' OR body ILIKE '%%suspicious%%')
            ORDER BY updated_at DESC LIMIT 12
        """)
        candidates = fetch_dicts(cur, """
            SELECT sr.* FROM scanner_results sr
            JOIN (SELECT max(id) AS run_id FROM scanner_runs) latest ON latest.run_id=sr.run_id
            WHERE sr.liquidity_pass=true
            ORDER BY sr.score DESC LIMIT 15
        """)
        insider_leads = fetch_dicts(cur, """
            SELECT ticker_symbols[1] AS ticker, freshness AS status, round((confidence*100)::numeric, 1) AS score,
                   title AS recommended_use, body AS positive_factors, '' AS risk_flags,
                   0 AS open_market_buy_count, 0 AS distinct_buyers, 0 AS total_buy_value,
                   '' AS role_quality, '' AS materiality_label, '' AS liquidity_label
            FROM agent_artifacts
            WHERE artifact_type='insider_buying_lead'
            ORDER BY updated_at DESC LIMIT 10
        """)
        counts = {}
        for table in ['knowledge_chunks','agent_artifacts','recommendations','scanner_results','alpha_search_reports','alpha_leads','alpha_lead_evidence','alpha_handoffs']:
            cur.execute(f'SELECT COUNT(*) FROM {table}')
            counts[table] = int(cur.fetchone()[0])
    alpha_snapshot = status_snapshot()  # default path now uses Postgres for live status

    smoke_mode = os.getenv('WOLFY_CONTEXT_SMOKE') == '1'
    run_id = None
    if not smoke_mode:
        with connect(PG_DSN) as conn:
            run_id = start_agent_run(conn, agent_name='Wolfy', role='alpha_scout', job_id='wolfy-alpha-search-report', status='started', summary='Standalone alpha search context loaded.')

    print('Wolfy standalone Alpha Search Report context')
    print('Wolfy DB=Postgres primary; SQLite retired for live Alpha Search context')
    print_eod_governance()
    print('Postgres counts: ' + ', '.join(f'{k}={v}' for k, v in counts.items()))
    if run_id is None:
        print('Postgres agent run: skipped because WOLFY_CONTEXT_SMOKE=1')
    else:
        print(f'Postgres agent run: AGENT_RUN_ID={run_id}')
        print(f'After report/lead DB writes, run: python3 {CLI} run-finish --run-id {run_id} --status completed --records-created <N> --summary "<alpha leads/report summary>"')
        print(f'If blocked, run: python3 {CLI} run-finish --run-id {run_id} --status blocked --error-message "<specific blocker>" --summary "<specific blocker>"')
    print(f'Persist Alpha Search JSON using `python3 {ALPHA_PIPELINE} template`, then `python3 {ALPHA_PIPELINE} record --json <payload.json>`. Live record writes Postgres only.')
    print('Purpose: lead generation only. Do not approve trades. Be brief; no filler. Challenge weak leads and recommend no-trade when evidence is thin.')
    print('Required sections: insider buying, filings/news/catalysts, public social/free scanner status, suspicious-activity filters, top alpha leads, what Yang needs, what Sentinel must challenge.')
    print('Knowledge notes/rules relevant to this report:')
    for n in notes:
        print(f"- NOTE {n['topic']} tags={n['tags']}: {n['summary']}")
    for r in rules:
        print(f"- RULE {r['rule_name']} [{r['rule_type']}]: {r['description']}")
    print('Scanner lead pool:')
    for c in candidates:
        print(f"- {c['ticker']}: score={c['score']} close={c['close']} r5={c['r5']} r20={c['r20']} vs20={c['vs20']} vs50={c['vs50']} avg_vol={c['avg_volume']} atr={c['atr']}")
    if insider_leads:
        print('Recent insider-buying leads (support only, not triggers):')
        for lead in insider_leads:
            print(f"- {lead['ticker']}: status={lead['status']} score={lead['score']} use={lead['recommended_use']} positives={str(lead['positive_factors'])[:240]} risks={lead['risk_flags']}")
    print('Stored Alpha Search pipeline snapshot:')
    print('Alpha counts: ' + ', '.join(f"{k}={v}" for k, v in alpha_snapshot['counts'].items()))
    for lead in alpha_snapshot.get('recent_leads', [])[:8]:
        print(f"- {lead['ticker']}: type={lead['lead_type']} status={lead['status']} evidence_quality={lead['evidence_quality_score']} suspicious={lead['suspicious_action']} complete_ticket={lead['complete_ticket']} title={lead['title']}")
    for h in alpha_snapshot.get('open_handoffs', [])[:8]:
        print(f"- HANDOFF {h['target_agent']} {h['task_type']} status={h['status']} priority={h['priority']}: {h['title']}")
    print('Alpha persistence requirements: every lead needs ticker, lead_type, thesis, evidence if possible, suspicious_activity decision, next_research_question, and Sentinel/Yang/Jonah handoffs unless rejected.')


if __name__ == '__main__':
    main()
