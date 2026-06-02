#!/usr/bin/env python3
"""Print context for the standalone Wolfy Alpha Search Report and start a Postgres run row."""
from __future__ import annotations

from pathlib import Path
import sqlite3

try:
    import psycopg
except Exception:
    psycopg = None

from wolfy_agent_coordination import connect, start_agent_run
from insider_buying import ensure_insider_tables
from alpha_search_pipeline import ensure_alpha_tables, status_snapshot
from eod_governance import print_eod_governance

DB = Path('/root/.hermes/wolfy/wolfy.db')
PG_DSN = 'dbname=wolfy user=root host=/var/run/postgresql'
CLI = Path('/root/.hermes/wolfy/wolfy_agent_cli.py')
ALPHA_PIPELINE = Path('/root/.hermes/wolfy/alpha_search_pipeline.py')


def main() -> None:
    ensure_insider_tables(DB)
    ensure_alpha_tables(DB)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    notes = con.execute("SELECT topic, summary, tags FROM knowledge_notes WHERE tags LIKE '%alpha%' OR tags LIKE '%insider%' OR tags LIKE '%twitter%' OR tags LIKE '%suspicious%' ORDER BY id DESC LIMIT 12").fetchall()
    rules = con.execute("SELECT rule_name, rule_type, description FROM strategy_rules WHERE enabled=1 AND (rule_name LIKE '%Alpha%' OR rule_name LIKE '%Insider%' OR rule_name LIKE '%Social%' OR rule_name LIKE '%Yang%' OR description LIKE '%suspicious%') ORDER BY id DESC LIMIT 12").fetchall()
    candidates = con.execute(
        """
        SELECT sr.* FROM scanner_results sr
        JOIN (SELECT max(id) AS run_id FROM scanner_runs) latest ON latest.run_id=sr.run_id
        WHERE sr.liquidity_pass=1
        ORDER BY sr.score DESC LIMIT 15
        """
    ).fetchall()
    insider_leads = con.execute(
        """
        SELECT ticker, evaluated_at, status, score, recommended_use, open_market_buy_count,
               distinct_buyers, total_buy_value, role_quality, materiality_label,
               liquidity_label, risk_flags, positive_factors
        FROM insider_leads
        ORDER BY evaluated_at DESC, score DESC LIMIT 10
        """
    ).fetchall()
    alpha_snapshot = status_snapshot(DB)
    counts = {t: con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ['knowledge_notes','strategy_rules','recommendations','scanner_results','insider_transactions','insider_leads','alpha_search_reports','alpha_leads','alpha_lead_evidence','alpha_handoffs']}
    con.close()

    with connect(PG_DSN) as conn:
        run_id = start_agent_run(conn, agent_name='Wolfy', role='alpha_scout', job_id='wolfy-alpha-search-report', status='started', summary='Standalone alpha search context loaded.')

    print('Wolfy standalone Alpha Search Report context')
    print(f'SQLite DB={DB}')
    print_eod_governance()
    print('SQLite counts: ' + ', '.join(f'{k}={v}' for k, v in counts.items()))
    print(f'Postgres agent run: AGENT_RUN_ID={run_id}')
    print(f'After report/lead DB writes, run: python3 {CLI} run-finish --run-id {run_id} --status completed --records-created <N> --summary "<alpha leads/report summary>"')
    print(f'If blocked, run: python3 {CLI} run-finish --run-id {run_id} --status blocked --error-message "<specific blocker>" --summary "<specific blocker>"')
    print(f'Persist the Alpha Search Report before final answer: write JSON using template from `python3 {ALPHA_PIPELINE} template`, then run `python3 {ALPHA_PIPELINE} record --json <payload.json>`. Use --no-postgres-tasks only for local tests.')
    print('Purpose: lead generation only. Do not approve trades. Alpha leads are research inputs, not intraday actionable recommendations. Label ideas as leads/watchlist unless they later pass EOD approved-strategy/deterministic-signal gates and are inserted as pending_review recommendations for Sentinel.')
    print('Insider-buying rule: use public SEC Form 4/free legal sources; count only transaction-code P open-market buys; reject awards/exercises/conversions/sales as bullish evidence; treat qualified buys as thesis support only, never standalone triggers.')
    print('Required sections: insider buying leads, filings/news/catalysts, public social chatter/free-X-scanner status, suspicious-activity filters, top alpha leads for Wolfy review, what Yang needs technically, what Sentinel must challenge.')
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
            print(f"- {lead['ticker']}: status={lead['status']} score={lead['score']} use={lead['recommended_use']} buys={lead['open_market_buy_count']} buyers={lead['distinct_buyers']} value={lead['total_buy_value']} role={lead['role_quality']} materiality={lead['materiality_label']} liquidity={lead['liquidity_label']} positives={lead['positive_factors']} risks={lead['risk_flags']}")
    print('Stored Alpha Search pipeline snapshot:')
    print('Alpha counts: ' + ', '.join(f"{k}={v}" for k, v in alpha_snapshot['counts'].items()))
    if alpha_snapshot['recent_leads']:
        print('Recent stored alpha leads:')
        for lead in alpha_snapshot['recent_leads']:
            print(f"- {lead['ticker']}: type={lead['lead_type']} status={lead['status']} evidence_quality={lead['evidence_quality_score']} suspicious={lead['suspicious_action']} complete_ticket={lead['complete_ticket']} title={lead['title']}")
    if alpha_snapshot['open_handoffs']:
        print('Open alpha handoffs:')
        for h in alpha_snapshot['open_handoffs']:
            print(f"- {h['target_agent']} {h['task_type']} status={h['status']} priority={h['priority']}: {h['title']}")
    print('Alpha persistence requirements: every lead needs ticker, lead_type, thesis, at least one source/evidence row if possible, suspicious_activity decision, next_research_question, and Sentinel/Yang handoffs unless explicitly rejected/vetoed.')
    if psycopg is not None:
        try:
            with psycopg.connect(PG_DSN) as pg, pg.cursor() as cur:
                cur.execute("SELECT status, count(*) FROM agent_runs WHERE agent_name='Wolfy' AND role='alpha_scout' GROUP BY status ORDER BY status")
                rows = cur.fetchall()
                if rows:
                    print('Postgres Wolfy alpha_scout agent_runs: ' + ', '.join(f'{s}={c}' for s, c in rows))
        except Exception as e:
            print(f'Postgres run table unavailable: {type(e).__name__}: {e}')


if __name__ == '__main__':
    main()
