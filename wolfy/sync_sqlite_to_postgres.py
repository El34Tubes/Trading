#!/usr/bin/env python3
"""Seed/sync current Wolfy SQLite knowledge into Postgres search tables.

SQLite remains source-of-truth during transition; Postgres is prepared for
cross-agent oversight, full-text/trigram search, and pgvector embeddings.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

SQLITE_DB = Path('/root/.hermes/wolfy/wolfy.db')
PG_DSN = 'dbname=wolfy user=root host=/var/run/postgresql'

# User policy, 2026-07-09: keep vector/token retrieval focused on technical
# swing-trading strategy and standing guardrails. Fundamental/catalyst/filing
# source rows may remain as audit/source data, but should not be reinserted into
# knowledge_chunks where they consume retrieval context.
TECH_RE = re.compile(
    r"\b(technical|volume|trend|momentum|relative strength|moving average|\bSMA\b|\bEMA\b|\bATR\b|\bRSI\b|\bMACD\b|breakout|pullback|setup|trigger|stop|invalidation|support|resistance|volatility|consolidation|base|stage|Weinstein|Darvas|chart|gap|mean reversion|wedge|channel|entry|exit|risk/reward|position[- ]size|R multiple|sector rotation|market breadth|52[- ]week|high tight flag|vwap|trendline|trailing stop|Yang|Minervini)\b",
    re.I,
)
CORE_GUARDRAIL_RE = re.compile(
    r"\b(eod|end[- ]of[- ]day|no[-_ ]?(auto|trade|action|recommendation)|fact[-_ ]?vs[-_ ]?judgment|research[-_ ]only|risk control|data quality|backtest|evaluation|portfolio|universe|Robinhood|PDT|pattern day|long[- ]only|max three|human approval|guardrail|approved strategy|do not|must not|cannot|quality gate)\b",
    re.I,
)
EXPLICIT_NONTECH_RE = re.compile(
    r"\b(SEC|filing|10[- ]?K|10[- ]?Q|8[- ]?K|Form [A-Z0-9-]+|13F|13D|13G|Section 16|insider|ownership|shareholder|governance|compensation|accounting|financial statement|balance sheet|cash flow|cashflow|dcf|revenue|earnings|ARR|EBITDA|valuation|Graham|margin of safety|analyst|rating|price target|merger|acquisition|contract|guidance|gross margin|product|catalyst|dilution|warrant|offering|convertible|debt|covenant|auditor|legal proceedings|MD&A)\b",
    re.I,
)


def keep_for_technical_retrieval(source_table: str, body: str) -> bool:
    """Return whether a row belongs in knowledge_chunks retrieval.

    Source tables remain intact; this only limits the vector/trigram retrieval
    surface to technical setups and broad account/risk guardrails.
    """
    if source_table not in {'sqlite.knowledge_notes', 'sqlite.strategy_rules'}:
        return False
    is_technical = bool(TECH_RE.search(body))
    is_guardrail = bool(CORE_GUARDRAIL_RE.search(body))
    is_explicit_nontech = bool(EXPLICIT_NONTECH_RE.search(body))
    protected_yang_technical = body.lstrip().startswith(('Rule: Yang', 'Topic: Yang')) and is_technical
    return (is_technical or is_guardrail) and not (is_explicit_nontech and not protected_yang_technical)


def fingerprint(*parts: object) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p or '').encode())
        h.update(b'\0')
    return h.hexdigest()


def main() -> None:
    src = sqlite3.connect(SQLITE_DB)
    src.row_factory = sqlite3.Row
    inserted = 0
    with psycopg.connect(PG_DSN) as conn:
        with conn.cursor() as cur:
            notes = src.execute('SELECT * FROM knowledge_notes ORDER BY id').fetchall()
            for r in notes:
                body = f"Topic: {r['topic']}\nPrinciple: {r['principle']}\nSummary: {r['summary']}\nApplication to Wolfy: {r['application_to_wolfy']}"
                fp = fingerprint('sqlite.knowledge_notes', r['id'], body)
                cur.execute(
                    """
                    INSERT INTO agent_artifacts
                      (agent_name, artifact_type, title, body, source_fingerprint, topic_tags, confidence, freshness)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (artifact_type, source_fingerprint, title)
                    DO UPDATE SET body=EXCLUDED.body, updated_at=now()
                    RETURNING id
                    """,
                    ('Jonah', 'knowledge_note', r['topic'], body, fp, [t.strip() for t in (r['tags'] or '').split(',') if t.strip()], r['confidence'] or 0.5, 'durable'),
                )
                artifact_id = cur.fetchone()[0]
                if keep_for_technical_retrieval('sqlite.knowledge_notes', body):
                    cur.execute(
                        """
                        INSERT INTO knowledge_chunks (artifact_id, source_table, source_id, chunk_index, content, metadata)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (source_table, source_id, chunk_index)
                        DO UPDATE SET content=EXCLUDED.content, metadata=EXCLUDED.metadata
                        """,
                        (artifact_id, 'sqlite.knowledge_notes', str(r['id']), 0, body, Jsonb({'source': 'sqlite', 'table': 'knowledge_notes'})),
                    )
                else:
                    cur.execute(
                        "DELETE FROM knowledge_chunks WHERE source_table=%s AND source_id=%s",
                        ('sqlite.knowledge_notes', str(r['id'])),
                    )
                inserted += 1

            rules = src.execute('SELECT * FROM strategy_rules ORDER BY id').fetchall()
            for r in rules:
                body = f"Rule: {r['rule_name']}\nType: {r['rule_type']}\nDescription: {r['description']}\nSource basis: {r['source_basis']}\nStatus: {r['implementation_status']}\nEnabled: {r['enabled']}"
                fp = fingerprint('sqlite.strategy_rules', r['id'], body)
                cur.execute(
                    """
                    INSERT INTO agent_artifacts
                      (agent_name, artifact_type, title, body, source_fingerprint, topic_tags, confidence, freshness)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (artifact_type, source_fingerprint, title)
                    DO UPDATE SET body=EXCLUDED.body, updated_at=now()
                    RETURNING id
                    """,
                    ('Jonah', 'strategy_rule', r['rule_name'], body, fp, [r['rule_type']], 0.75, 'durable'),
                )
                artifact_id = cur.fetchone()[0]
                if keep_for_technical_retrieval('sqlite.strategy_rules', body):
                    cur.execute(
                        """
                        INSERT INTO knowledge_chunks (artifact_id, source_table, source_id, chunk_index, content, metadata)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (source_table, source_id, chunk_index)
                        DO UPDATE SET content=EXCLUDED.content, metadata=EXCLUDED.metadata
                        """,
                        (artifact_id, 'sqlite.strategy_rules', str(r['id']), 0, body, Jsonb({'source': 'sqlite', 'table': 'strategy_rules'})),
                    )
                else:
                    cur.execute(
                        "DELETE FROM knowledge_chunks WHERE source_table=%s AND source_id=%s",
                        ('sqlite.strategy_rules', str(r['id'])),
                    )
                inserted += 1

            try:
                insider_leads = src.execute('SELECT * FROM insider_leads ORDER BY id').fetchall()
            except sqlite3.OperationalError:
                insider_leads = []
            for r in insider_leads:
                body = (
                    f"Ticker: {r['ticker']}\nStatus: {r['status']}\nScore: {r['score']}\n"
                    f"Recommended use: {r['recommended_use']}\nOpen-market buys: {r['open_market_buy_count']}\n"
                    f"Distinct buyers: {r['distinct_buyers']}\nTotal buy value: {r['total_buy_value']}\n"
                    f"Role quality: {r['role_quality']}\nMateriality: {r['materiality_label']}\nLiquidity: {r['liquidity_label']}\n"
                    f"Risk flags: {r['risk_flags']}\nPositive factors: {r['positive_factors']}\nNotes: {r['notes']}"
                )
                fp = fingerprint('sqlite.insider_leads', r['id'], r['evaluated_at'], body)
                cur.execute(
                    """
                    INSERT INTO agent_artifacts
                      (agent_name, artifact_type, title, body, source_fingerprint, topic_tags, ticker_symbols, confidence, freshness)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (artifact_type, source_fingerprint, title)
                    DO UPDATE SET body=EXCLUDED.body, updated_at=now()
                    RETURNING id
                    """,
                    ('Wolfy', 'insider_buying_lead', f"{r['ticker']} insider-buying support lead", body, fp, ['insider_buying', 'form4', r['status']], [r['ticker']], min(0.95, max(0.1, (r['score'] or 0) / 100)), 'current'),
                )
                artifact_id = cur.fetchone()[0]
                cur.execute(
                    "DELETE FROM knowledge_chunks WHERE source_table=%s AND source_id=%s",
                    ('sqlite.insider_leads', str(r['id'])),
                )
                inserted += 1
            try:
                alpha_leads = src.execute('SELECT * FROM alpha_leads ORDER BY id').fetchall()
            except sqlite3.OperationalError:
                alpha_leads = []
            for r in alpha_leads:
                body = (
                    f"Ticker: {r['ticker']}\nLead type: {r['lead_type']}\nStatus: {r['status']}\nTitle: {r['title']}\n"
                    f"Thesis: {r['thesis']}\nEvidence quality: {r['evidence_quality_score']} count={r['evidence_count']} max_source={r['highest_source_quality']}\n"
                    f"Suspicious action: {r['suspicious_action']} flags={r['suspicious_flags_json']}\n"
                    f"Catalyst window: {r['catalyst_window']}\nFiling context: {r['filing_context']}\n"
                    f"Insider context: {r['insider_context']}\nSocial context: {r['social_context']}\n"
                    f"Complete ticket: {r['complete_ticket']} recommendation_id={r['recommendation_id']}\n"
                    f"Next research question: {r['next_research_question']}"
                )
                fp = r['source_fingerprint'] or fingerprint('sqlite.alpha_leads', r['id'], body)
                cur.execute(
                    """
                    INSERT INTO agent_artifacts
                      (agent_name, artifact_type, title, body, source_fingerprint, topic_tags, ticker_symbols, confidence, freshness)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (artifact_type, source_fingerprint, title)
                    DO UPDATE SET body=EXCLUDED.body, updated_at=now()
                    RETURNING id
                    """,
                    ('Wolfy', 'alpha_search_lead', r['title'], body, fp, ['alpha_search', r['lead_type'], r['status'], r['suspicious_action']], [r['ticker']], min(0.95, max(0.05, float(r['evidence_quality_score'] or 0))), 'current'),
                )
                artifact_id = cur.fetchone()[0]
                cur.execute(
                    "DELETE FROM knowledge_chunks WHERE source_table=%s AND source_id=%s",
                    ('sqlite.alpha_leads', str(r['id'])),
                )
                cur.execute(
                    """
                    INSERT INTO alpha_leads(
                      sqlite_id, ticker, lead_type, title, thesis, status, evidence_quality_score,
                      evidence_count, highest_source_quality, suspicious_action, suspicious_flags,
                      catalyst_window, social_context, filing_context, insider_context, complete_ticket,
                      recommendation_id, next_research_question, raw_payload, source_fingerprint
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (sqlite_id) DO UPDATE SET
                      ticker=EXCLUDED.ticker, lead_type=EXCLUDED.lead_type, title=EXCLUDED.title,
                      thesis=EXCLUDED.thesis, status=EXCLUDED.status,
                      evidence_quality_score=EXCLUDED.evidence_quality_score,
                      evidence_count=EXCLUDED.evidence_count,
                      highest_source_quality=EXCLUDED.highest_source_quality,
                      suspicious_action=EXCLUDED.suspicious_action,
                      suspicious_flags=EXCLUDED.suspicious_flags,
                      catalyst_window=EXCLUDED.catalyst_window,
                      social_context=EXCLUDED.social_context,
                      filing_context=EXCLUDED.filing_context,
                      insider_context=EXCLUDED.insider_context,
                      complete_ticket=EXCLUDED.complete_ticket,
                      recommendation_id=EXCLUDED.recommendation_id,
                      next_research_question=EXCLUDED.next_research_question,
                      raw_payload=EXCLUDED.raw_payload,
                      source_fingerprint=EXCLUDED.source_fingerprint,
                      updated_at=now()
                    """,
                    (
                        r['id'], r['ticker'], r['lead_type'], r['title'], r['thesis'], r['status'],
                        r['evidence_quality_score'], r['evidence_count'], r['highest_source_quality'],
                        r['suspicious_action'], Jsonb(json.loads(r['suspicious_flags_json'] or '[]')),
                        r['catalyst_window'], r['social_context'], r['filing_context'], r['insider_context'],
                        bool(r['complete_ticket']), str(r['recommendation_id']) if r['recommendation_id'] else None,
                        r['next_research_question'], Jsonb(json.loads(r['raw_payload_json'] or '{}')), fp,
                    ),
                )
                inserted += 1
        conn.commit()
    print(f'synced_artifacts={inserted}')


if __name__ == '__main__':
    main()
