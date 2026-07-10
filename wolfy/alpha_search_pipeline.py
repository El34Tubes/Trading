#!/usr/bin/env python3
"""Persistent Alpha Search Report pipeline for Wolfy.

The Alpha Search Report is a lead-generation product, not a trade-approval
product. This module gives the scheduled LLM run a deterministic way to store:

- the report artifact and its required sections;
- individual alpha leads with evidence-quality scoring and source links;
- suspicious-activity flags/decisions;
- handoff requests for Wolfy/Sentinel/Yang follow-up.

Postgres is the source of truth. SQLite helpers remain only for isolated legacy tests; live cron paths write Postgres directly and fail loudly if Postgres is unavailable.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping

try:
    import psycopg
    from psycopg.types.json import Jsonb
except Exception:  # pragma: no cover - live Postgres path validates availability
    psycopg = None
    Jsonb = None

from suspicious_activity import SUSPICIOUS_SCHEMA, evaluate_recommendation_suspicion

try:  # Optional: present on the live Wolfy box, absent in isolated tests.
    from wolfy_agent_coordination import connect, ensure_agent_task, stable_fingerprint
except Exception:  # pragma: no cover - exercised only in stripped-down envs
    connect = None
    ensure_agent_task = None

    def stable_fingerprint(*parts: object) -> str:
        h = hashlib.sha256()
        for p in parts:
            h.update(str(p or "").encode("utf-8"))
            h.update(b"\0")
        return h.hexdigest()


DEFAULT_DB = Path("/root/.hermes/wolfy/wolfy.db")
DEFAULT_PG_DSN = "dbname=wolfy user=root host=/var/run/postgresql"
REQUIRED_SECTIONS = [
    "insider_buying",
    "filings_news_catalysts",
    "social_scanner",
    "suspicious_activity",
    "top_alpha_leads",
    "deeper_research_needed",
    "yang_needs",
    "sentinel_challenges",
]
VALID_STATUSES = {"new", "watchlist", "needs_research", "sent_to_wolfy", "sent_to_sentinel", "sent_to_yang", "rejected", "archived"}
VALID_HANDOFF_AGENTS = {"Wolfy", "Sentinel", "Yang", "Jonah"}

ALPHA_SCHEMA = """
CREATE TABLE IF NOT EXISTS alpha_search_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  source_job_id TEXT NOT NULL DEFAULT 'wolfy-alpha-search-report',
  agent_run_id TEXT,
  title TEXT NOT NULL,
  market_context TEXT,
  sections_json TEXT NOT NULL,
  summary TEXT NOT NULL,
  delivered_to TEXT,
  raw_payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alpha_reports_created ON alpha_search_reports(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alpha_reports_job ON alpha_search_reports(source_job_id, created_at DESC);

CREATE TABLE IF NOT EXISTS alpha_leads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  report_id INTEGER REFERENCES alpha_search_reports(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  ticker TEXT NOT NULL,
  lead_type TEXT NOT NULL,
  title TEXT NOT NULL,
  thesis TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new',
  evidence_quality_score REAL NOT NULL DEFAULT 0.0,
  evidence_count INTEGER NOT NULL DEFAULT 0,
  highest_source_quality REAL NOT NULL DEFAULT 0.0,
  suspicious_action TEXT NOT NULL DEFAULT 'clear',
  suspicious_flags_json TEXT NOT NULL DEFAULT '[]',
  catalyst_window TEXT,
  social_context TEXT,
  filing_context TEXT,
  insider_context TEXT,
  complete_ticket INTEGER NOT NULL DEFAULT 0,
  recommendation_id INTEGER REFERENCES recommendations(id),
  next_research_question TEXT,
  company_name TEXT,
  scanner_type TEXT,
  score REAL,
  raw_payload_json TEXT NOT NULL,
  source_fingerprint TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_alpha_leads_ticker_status ON alpha_leads(ticker, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_alpha_leads_quality ON alpha_leads(evidence_quality_score DESC, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_alpha_leads_suspicious ON alpha_leads(suspicious_action, updated_at DESC);

CREATE TABLE IF NOT EXISTS alpha_lead_evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id INTEGER NOT NULL REFERENCES alpha_leads(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  evidence_type TEXT NOT NULL,
  source_title TEXT,
  source_url TEXT,
  source_published_at TEXT,
  quote_or_fact TEXT NOT NULL,
  quality_score REAL NOT NULL DEFAULT 0.5,
  relevance_score REAL NOT NULL DEFAULT 0.5,
  notes TEXT,
  source_fingerprint TEXT NOT NULL,
  UNIQUE(lead_id, source_fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_alpha_evidence_lead ON alpha_lead_evidence(lead_id, quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_alpha_evidence_url ON alpha_lead_evidence(source_url);

CREATE TABLE IF NOT EXISTS alpha_handoffs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id INTEGER REFERENCES alpha_leads(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  target_agent TEXT NOT NULL,
  task_type TEXT NOT NULL,
  title TEXT NOT NULL,
  question TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 50,
  status TEXT NOT NULL DEFAULT 'queued',
  postgres_task_id TEXT,
  source_fingerprint TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_alpha_handoffs_agent_status ON alpha_handoffs(target_agent, status, priority, created_at);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")




def ensure_alpha_tables_postgres(pg_dsn: str | None = DEFAULT_PG_DSN) -> None:
    """Ensure Alpha Search tables exist in Postgres. No SQLite fallback."""
    if psycopg is None or Jsonb is None:
        raise RuntimeError("psycopg is unavailable; cannot use Postgres-only alpha pipeline")
    statements = [
        """
        CREATE TABLE IF NOT EXISTS alpha_search_reports (
          id BIGSERIAL PRIMARY KEY,
          sqlite_id BIGINT UNIQUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          source_job_id TEXT NOT NULL DEFAULT 'wolfy-alpha-search-report',
          agent_run_id TEXT,
          title TEXT NOT NULL,
          market_context TEXT,
          sections JSONB NOT NULL DEFAULT '{}'::jsonb,
          summary TEXT NOT NULL,
          delivered_to TEXT,
          raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_pg_alpha_reports_created ON alpha_search_reports(created_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS alpha_leads (
          id BIGSERIAL PRIMARY KEY,
          sqlite_id BIGINT UNIQUE,
          report_id BIGINT REFERENCES alpha_search_reports(id) ON DELETE SET NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          ticker TEXT NOT NULL,
          lead_type TEXT NOT NULL,
          title TEXT NOT NULL,
          thesis TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'new',
          evidence_quality_score NUMERIC(5,3) NOT NULL DEFAULT 0,
          evidence_quality NUMERIC(5,3),
          evidence_count INTEGER NOT NULL DEFAULT 0,
          highest_source_quality NUMERIC(5,3) NOT NULL DEFAULT 0,
          suspicious_action TEXT NOT NULL DEFAULT 'clear',
          suspicious_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
          risk_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
          catalyst_window TEXT,
          social_context TEXT,
          filing_context TEXT,
          insider_context TEXT,
          complete_ticket BOOLEAN NOT NULL DEFAULT false,
          recommendation_id TEXT,
          next_research_question TEXT,
          company_name TEXT,
          scanner_type TEXT,
          market_context JSONB,
          score DOUBLE PRECISION,
          raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          source_fingerprint TEXT NOT NULL UNIQUE
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_pg_alpha_leads_ticker_status ON alpha_leads(ticker, status, updated_at DESC)",
        "ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS risk_flags JSONB NOT NULL DEFAULT '[]'",
        "UPDATE alpha_leads SET risk_flags=COALESCE(NULLIF(risk_flags, '[]'::jsonb), raw_payload->'risk_flags', suspicious_flags, raw_payload->'suspicious_flags', '[]'::jsonb) WHERE risk_flags IS NULL OR risk_flags = '[]'::jsonb",
        "ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS evidence_quality NUMERIC(5,3)",
        "UPDATE alpha_leads SET evidence_quality=COALESCE(evidence_quality, evidence_quality_score) WHERE evidence_quality IS NULL",
        "ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS market_context JSONB",
        "UPDATE alpha_leads SET market_context=COALESCE(market_context, raw_payload->'market_context') WHERE market_context IS NULL",
        """
        CREATE TABLE IF NOT EXISTS alpha_lead_evidence (
          id BIGSERIAL PRIMARY KEY,
          sqlite_id BIGINT UNIQUE,
          lead_id BIGINT NOT NULL REFERENCES alpha_leads(id) ON DELETE CASCADE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          evidence_type TEXT NOT NULL,
          source_title TEXT,
          source_url TEXT,
          source_published_at TEXT,
          quote_or_fact TEXT NOT NULL,
          quality_score NUMERIC(5,3) NOT NULL DEFAULT 0.5,
          relevance_score NUMERIC(5,3) NOT NULL DEFAULT 0.5,
          notes TEXT,
          source_fingerprint TEXT NOT NULL,
          UNIQUE(lead_id, source_fingerprint)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS alpha_handoffs (
          id BIGSERIAL PRIMARY KEY,
          sqlite_id BIGINT UNIQUE,
          lead_id BIGINT REFERENCES alpha_leads(id) ON DELETE CASCADE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          target_agent TEXT NOT NULL,
          task_type TEXT NOT NULL,
          title TEXT NOT NULL,
          question TEXT NOT NULL,
          priority INTEGER NOT NULL DEFAULT 50,
          status TEXT NOT NULL DEFAULT 'queued',
          postgres_task_id BIGINT REFERENCES agent_tasks(id),
          source_fingerprint TEXT NOT NULL UNIQUE
        )
        """,
    ]
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)
        conn.commit()


def record_alpha_payload_postgres(
    payload: Mapping[str, Any],
    *,
    pg_dsn: str | None = DEFAULT_PG_DSN,
    create_postgres_tasks: bool = True,
) -> RecordResult:
    """Persist Alpha Search payload to Postgres only; no SQLite writes."""
    if psycopg is None or Jsonb is None:
        raise RuntimeError("psycopg is unavailable; cannot use Postgres-only alpha pipeline")
    ensure_alpha_tables_postgres(pg_dsn)
    leads_upserted = evidence_seen = handoffs_seen = pg_created = 0
    report_obj = payload.get("report") if isinstance(payload.get("report"), Mapping) else payload
    sections = dict(report_obj.get("sections") or {})
    missing = [sec for sec in REQUIRED_SECTIONS if sec not in sections]
    if missing:
        sections["missing_sections"] = missing
    source_job_id = str(report_obj.get("source_job_id") or payload.get("source_job_id") or "wolfy-alpha-search-report")
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO alpha_search_reports(source_job_id,agent_run_id,title,market_context,sections,summary,delivered_to,raw_payload)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
            """,
            (
                source_job_id,
                str(report_obj.get("agent_run_id") or payload.get("agent_run_id") or "") or None,
                str(report_obj.get("title") or "Wolfy Alpha Search Report"),
                report_obj.get("market_context"),
                Jsonb(sections),
                str(report_obj.get("summary") or payload.get("summary") or "Alpha search report stored."),
                report_obj.get("delivered_to"),
                Jsonb(dict(payload)),
            ),
        )
        report_id = int(cur.fetchone()[0])
        for lead in payload.get("leads", []) or []:
            ticker = _ticker(lead.get("ticker"))
            if not ticker:
                continue
            evidence = list(lead.get("evidence") or [])
            score, evidence_count, max_q = evidence_quality(evidence)
            suspicion = _suspicion_for_lead(lead)
            complete_ticket = bool(lead.get("complete_ticket") or lead.get("recommendation_id"))
            status = _coerce_status(lead.get("status") or ("needs_research" if not complete_ticket else "sent_to_sentinel"))
            lead_fp = _lead_fingerprint(source_job_id, lead)
            cur.execute(
                """
                INSERT INTO alpha_leads(
                  report_id,ticker,lead_type,title,thesis,status,evidence_quality_score,
                  evidence_count,highest_source_quality,suspicious_action,suspicious_flags,
                  catalyst_window,social_context,filing_context,insider_context,complete_ticket,
                  recommendation_id,next_research_question,raw_payload,source_fingerprint,updated_at
                ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT(source_fingerprint) DO UPDATE SET
                  report_id=excluded.report_id,status=excluded.status,evidence_quality_score=excluded.evidence_quality_score,
                  evidence_count=excluded.evidence_count,highest_source_quality=excluded.highest_source_quality,
                  suspicious_action=excluded.suspicious_action,suspicious_flags=excluded.suspicious_flags,
                  catalyst_window=excluded.catalyst_window,social_context=excluded.social_context,
                  filing_context=excluded.filing_context,insider_context=excluded.insider_context,
                  complete_ticket=excluded.complete_ticket,recommendation_id=excluded.recommendation_id,
                  next_research_question=excluded.next_research_question,raw_payload=excluded.raw_payload,updated_at=now()
                RETURNING id
                """,
                (
                    report_id, ticker, str(lead.get("lead_type") or "general_alpha"),
                    str(lead.get("title") or f"{ticker} alpha lead"),
                    str(lead.get("thesis") or "Needs deeper research before any trade decision."),
                    status, score, evidence_count, max_q, str(suspicion.get("recommended_action") or "clear"),
                    Jsonb(list(suspicion.get("flags") or [])), lead.get("catalyst_window"), lead.get("social_context"),
                    lead.get("filing_context"), lead.get("insider_context"), complete_ticket,
                    str(lead.get("recommendation_id")) if lead.get("recommendation_id") else None,
                    lead.get("next_research_question"), Jsonb(dict(lead)), lead_fp,
                ),
            )
            lead_id = int(cur.fetchone()[0])
            leads_upserted += 1
            evidence_seen += len(evidence)
            for idx, e in enumerate(evidence):
                fact = e.get("quote_or_fact") or e.get("fact") or e.get("quote") or e.get("summary")
                if not fact:
                    continue
                ev_fp = str(e.get("source_fingerprint") or stable_fingerprint("alpha_evidence", lead_fp, idx, e.get("source_url"), fact))
                cur.execute(
                    """
                    INSERT INTO alpha_lead_evidence(lead_id,evidence_type,source_title,source_url,source_published_at,quote_or_fact,quality_score,relevance_score,notes,source_fingerprint)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(lead_id, source_fingerprint) DO NOTHING
                    """,
                    (
                        lead_id, str(e.get("evidence_type") or e.get("type") or "source"),
                        e.get("source_title") or e.get("title"), e.get("source_url") or e.get("url"),
                        e.get("source_published_at") or e.get("published_at"), str(fact),
                        max(0.0, min(1.0, _coerce_float(e.get("quality_score"), 0.5))),
                        max(0.0, min(1.0, _coerce_float(e.get("relevance_score"), 0.5))), e.get("notes"), ev_fp,
                    ),
                )
            for handoff in lead.get("handoffs", []) or []:
                target = str(handoff.get("target_agent") or handoff.get("agent") or "").strip().title()
                if target not in VALID_HANDOFF_AGENTS:
                    continue
                question = str(handoff.get("question") or handoff.get("description") or lead.get("next_research_question") or "Review this alpha lead before any recommendation.")
                task_type = str(handoff.get("task_type") or f"alpha_{target.lower()}_review")
                title = str(handoff.get("title") or f"{target} review: {ticker} alpha lead")
                priority = int(handoff.get("priority") or 50)
                hf_fp = str(handoff.get("source_fingerprint") or stable_fingerprint("alpha_handoff", lead_fp, target, task_type, question))
                pg_task_id = None
                if create_postgres_tasks and connect is not None and ensure_agent_task is not None:
                    task = ensure_agent_task(
                        conn, agent_name=target, task_type=task_type, title=title, description=question,
                        source_fingerprint=hf_fp, topic_tags=["alpha_search", "handoff"],
                        ticker_symbols=[ticker], priority=priority,
                    )
                    pg_task_id = task.id
                    if task.created:
                        pg_created += 1
                cur.execute(
                    """
                    INSERT INTO alpha_handoffs(lead_id,target_agent,task_type,title,question,priority,status,postgres_task_id,source_fingerprint)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(source_fingerprint) DO UPDATE SET postgres_task_id=COALESCE(excluded.postgres_task_id, alpha_handoffs.postgres_task_id), status=excluded.status
                    """,
                    (lead_id, target, task_type, title, question, priority, "queued", pg_task_id, hf_fp),
                )
                handoffs_seen += 1
        conn.commit()
    return RecordResult(report_id, len(payload.get("leads", []) or []), leads_upserted, evidence_seen, handoffs_seen, pg_created)

def ensure_alpha_tables(db_path: str | Path = DEFAULT_DB) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        con.executescript(SUSPICIOUS_SCHEMA)
        con.executescript(ALPHA_SCHEMA)
        con.commit()
    finally:
        con.close()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_status(value: Any) -> str:
    status = str(value or "new").strip().lower().replace(" ", "_")
    return status if status in VALID_STATUSES else "new"


def _ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def evidence_quality(evidence: Iterable[Mapping[str, Any]]) -> tuple[float, int, float]:
    rows = list(evidence or [])
    if not rows:
        return 0.0, 0, 0.0
    weighted = 0.0
    total_weight = 0.0
    max_q = 0.0
    for e in rows:
        q = max(0.0, min(1.0, _coerce_float(e.get("quality_score"), 0.5)))
        r = max(0.0, min(1.0, _coerce_float(e.get("relevance_score"), 0.5)))
        has_url_bonus = 0.05 if str(e.get("source_url") or "").startswith(("http://", "https://")) else 0.0
        item_score = min(1.0, (q * 0.7) + (r * 0.25) + has_url_bonus)
        weight = 1.0 + r
        weighted += item_score * weight
        total_weight += weight
        max_q = max(max_q, q)
    coverage_bonus = min(0.15, 0.03 * len(rows))
    return round(min(1.0, (weighted / max(total_weight, 1.0)) + coverage_bonus), 3), len(rows), round(max_q, 3)


def _lead_fingerprint(report_source_job_id: str, lead: Mapping[str, Any]) -> str:
    supplied = lead.get("source_fingerprint") or lead.get("fingerprint")
    if supplied:
        return str(supplied)
    evidence_keys = [
        f"{e.get('source_url','')}|{e.get('quote_or_fact') or e.get('fact') or e.get('quote') or ''}"
        for e in lead.get("evidence", [])
    ]
    return stable_fingerprint(
        "alpha_lead",
        report_source_job_id,
        _ticker(lead.get("ticker")),
        lead.get("lead_type"),
        lead.get("title"),
        lead.get("thesis"),
        "\n".join(sorted(evidence_keys)),
    )


def _suspicion_for_lead(lead: Mapping[str, Any]) -> dict[str, Any]:
    supplied = lead.get("suspicious_activity") or lead.get("suspicion")
    if isinstance(supplied, Mapping) and supplied.get("recommended_action"):
        return {
            "ticker": _ticker(lead.get("ticker")),
            "recommended_action": str(supplied.get("recommended_action") or "caution"),
            "flags": list(supplied.get("flags") or []),
            "confidence_adjustment": supplied.get("confidence_adjustment"),
            "confidence_multiplier": supplied.get("confidence_multiplier"),
        }
    idea = {
        "ticker": _ticker(lead.get("ticker")),
        "thesis": lead.get("thesis"),
        "risk_notes": lead.get("risk_notes") or lead.get("next_research_question"),
        "social_context": lead.get("social_context"),
        "corporate_actions": lead.get("corporate_actions"),
        "market_context": lead.get("market_context") or {},
    }
    return evaluate_recommendation_suspicion(idea)


def _insert_report(con: sqlite3.Connection, payload: Mapping[str, Any]) -> int:
    report = payload.get("report") if isinstance(payload.get("report"), Mapping) else payload
    sections = dict(report.get("sections") or {})
    missing = [s for s in REQUIRED_SECTIONS if s not in sections]
    if missing:
        sections["missing_sections"] = missing
    cur = con.execute(
        """
        INSERT INTO alpha_search_reports(
          source_job_id, agent_run_id, title, market_context, sections_json,
          summary, delivered_to, raw_payload_json
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            str(report.get("source_job_id") or payload.get("source_job_id") or "wolfy-alpha-search-report"),
            str(report.get("agent_run_id") or payload.get("agent_run_id") or "") or None,
            str(report.get("title") or "Wolfy Alpha Search Report"),
            report.get("market_context"),
            _json_dumps(sections),
            str(report.get("summary") or payload.get("summary") or "Alpha search report stored."),
            report.get("delivered_to"),
            _json_dumps(payload),
        ),
    )
    return int(cur.lastrowid)


def _insert_evidence(con: sqlite3.Connection, lead_id: int, lead_fp: str, evidence: Iterable[Mapping[str, Any]]) -> int:
    inserted = 0
    for idx, e in enumerate(evidence or []):
        fact = e.get("quote_or_fact") or e.get("fact") or e.get("quote") or e.get("summary")
        if not fact:
            continue
        ev_fp = str(e.get("source_fingerprint") or stable_fingerprint("alpha_evidence", lead_fp, idx, e.get("source_url"), fact))
        con.execute(
            """
            INSERT OR IGNORE INTO alpha_lead_evidence(
              lead_id,evidence_type,source_title,source_url,source_published_at,
              quote_or_fact,quality_score,relevance_score,notes,source_fingerprint
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                lead_id,
                str(e.get("evidence_type") or e.get("type") or "source"),
                e.get("source_title") or e.get("title"),
                e.get("source_url") or e.get("url"),
                e.get("source_published_at") or e.get("published_at"),
                str(fact),
                max(0.0, min(1.0, _coerce_float(e.get("quality_score"), 0.5))),
                max(0.0, min(1.0, _coerce_float(e.get("relevance_score"), 0.5))),
                e.get("notes"),
                ev_fp,
            ),
        )
        inserted += con.total_changes > 0
    return inserted


def _persist_suspicious_flags_con(con: sqlite3.Connection, source_table: str, source_id: str, ticker: str, result: Mapping[str, Any]) -> int:
    inserted = 0
    for f in result.get("flags", []) or []:
        con.execute(
            """
            INSERT INTO suspicious_activity_flags(source_table,source_id,ticker,flag_type,severity,recommended_action,evidence)
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                source_table,
                str(source_id),
                str(ticker).upper(),
                f["flag_type"],
                f["severity"],
                result.get("recommended_action", "caution"),
                json.dumps(f.get("evidence", {}), sort_keys=True),
            ),
        )
        inserted += 1
    return inserted


@dataclass(frozen=True)
class RecordResult:
    report_id: int
    leads_seen: int
    leads_upserted: int
    evidence_rows_seen: int
    handoffs_seen: int
    postgres_tasks_created: int


def record_alpha_payload(
    payload: Mapping[str, Any],
    *,
    db_path: str | Path = DEFAULT_DB,
    pg_dsn: str | None = DEFAULT_PG_DSN,
    create_postgres_tasks: bool = True,
) -> RecordResult:
    # Live Wolfy is Postgres-only. Temp DB paths still use legacy SQLite for unit tests.
    if Path(db_path) == DEFAULT_DB:
        return record_alpha_payload_postgres(payload, pg_dsn=pg_dsn, create_postgres_tasks=create_postgres_tasks)
    ensure_alpha_tables(db_path)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    leads_upserted = 0
    evidence_seen = 0
    handoffs_seen = 0
    pg_created = 0
    try:
        report_id = _insert_report(con, payload)
        report_obj = payload.get("report") if isinstance(payload.get("report"), Mapping) else {}
        source_job_id = str(report_obj.get("source_job_id") or payload.get("source_job_id") or "wolfy-alpha-search-report")
        for lead in payload.get("leads", []) or []:
            ticker = _ticker(lead.get("ticker"))
            if not ticker:
                continue
            evidence = list(lead.get("evidence") or [])
            score, evidence_count, max_q = evidence_quality(evidence)
            suspicion = _suspicion_for_lead(lead)
            complete_ticket = bool(lead.get("complete_ticket") or lead.get("recommendation_id"))
            status = _coerce_status(lead.get("status") or ("needs_research" if not complete_ticket else "sent_to_sentinel"))
            lead_fp = _lead_fingerprint(source_job_id, lead)
            cur = con.execute(
                """
                INSERT INTO alpha_leads(
                  report_id,ticker,lead_type,title,thesis,status,evidence_quality_score,
                  evidence_count,highest_source_quality,suspicious_action,suspicious_flags_json,
                  catalyst_window,social_context,filing_context,insider_context,complete_ticket,
                  recommendation_id,next_research_question,raw_payload_json,source_fingerprint,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                ON CONFLICT(source_fingerprint) DO UPDATE SET
                  report_id=excluded.report_id,
                  status=excluded.status,
                  evidence_quality_score=excluded.evidence_quality_score,
                  evidence_count=excluded.evidence_count,
                  highest_source_quality=excluded.highest_source_quality,
                  suspicious_action=excluded.suspicious_action,
                  suspicious_flags_json=excluded.suspicious_flags_json,
                  catalyst_window=excluded.catalyst_window,
                  social_context=excluded.social_context,
                  filing_context=excluded.filing_context,
                  insider_context=excluded.insider_context,
                  complete_ticket=excluded.complete_ticket,
                  recommendation_id=excluded.recommendation_id,
                  next_research_question=excluded.next_research_question,
                  raw_payload_json=excluded.raw_payload_json,
                  updated_at=datetime('now')
                RETURNING id
                """,
                (
                    report_id,
                    ticker,
                    str(lead.get("lead_type") or "general_alpha"),
                    str(lead.get("title") or f"{ticker} alpha lead"),
                    str(lead.get("thesis") or "Needs deeper research before any trade decision."),
                    status,
                    score,
                    evidence_count,
                    max_q,
                    str(suspicion.get("recommended_action") or "clear"),
                    _json_dumps(suspicion.get("flags") or []),
                    lead.get("catalyst_window"),
                    lead.get("social_context"),
                    lead.get("filing_context"),
                    lead.get("insider_context"),
                    1 if complete_ticket else 0,
                    lead.get("recommendation_id"),
                    lead.get("next_research_question"),
                    _json_dumps(lead),
                    lead_fp,
                ),
            )
            lead_id = int(cur.fetchone()[0])
            leads_upserted += 1
            evidence_seen += len(evidence)
            _insert_evidence(con, lead_id, lead_fp, evidence)
            _persist_suspicious_flags_con(con, "alpha_leads", str(lead_id), ticker, suspicion)
            for handoff in lead.get("handoffs", []) or []:
                target = str(handoff.get("target_agent") or handoff.get("agent") or "").strip().title()
                if target not in VALID_HANDOFF_AGENTS:
                    continue
                question = str(handoff.get("question") or handoff.get("description") or lead.get("next_research_question") or "Review this alpha lead before any recommendation.")
                task_type = str(handoff.get("task_type") or f"alpha_{target.lower()}_review")
                title = str(handoff.get("title") or f"{target} review: {ticker} alpha lead")
                priority = int(handoff.get("priority") or 50)
                hf_fp = str(handoff.get("source_fingerprint") or stable_fingerprint("alpha_handoff", lead_fp, target, task_type, question))
                con.execute(
                    """
                    INSERT OR IGNORE INTO alpha_handoffs(
                      lead_id,target_agent,task_type,title,question,priority,source_fingerprint
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (lead_id, target, task_type, title, question, priority, hf_fp),
                )
                handoffs_seen += 1
        con.commit()

        if create_postgres_tasks and connect is not None and ensure_agent_task is not None and pg_dsn:
            with connect(pg_dsn) as pg:
                for row in con.execute("SELECT h.*, l.ticker FROM alpha_handoffs h LEFT JOIN alpha_leads l ON l.id=h.lead_id WHERE h.postgres_task_id IS NULL ORDER BY h.priority, h.id LIMIT 50").fetchall():
                    task = ensure_agent_task(
                        pg,
                        agent_name=row["target_agent"],
                        task_type=row["task_type"],
                        title=row["title"],
                        description=row["question"],
                        source_fingerprint=row["source_fingerprint"],
                        topic_tags=["alpha_search", "handoff"],
                        ticker_symbols=[row["ticker"]] if row["ticker"] else [],
                        priority=int(row["priority"]),
                    )
                    con.execute("UPDATE alpha_handoffs SET postgres_task_id=?, status=? WHERE id=?", (str(task.id), task.status, row["id"]))
                    if task.created:
                        pg_created += 1
                pg.commit()
                con.commit()
        return RecordResult(report_id, len(payload.get("leads", []) or []), leads_upserted, evidence_seen, handoffs_seen, pg_created)
    finally:
        con.close()


def status_snapshot(db_path: str | Path = DEFAULT_DB) -> dict[str, Any]:
    """Return Alpha Search status. Live default reads Postgres only; temp paths use legacy SQLite tests."""
    if Path(db_path) == DEFAULT_DB:
        ensure_alpha_tables_postgres(DEFAULT_PG_DSN)
        with psycopg.connect(DEFAULT_PG_DSN) as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM alpha_search_reports")
            reports = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM alpha_leads")
            leads = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM alpha_lead_evidence")
            evidence = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM alpha_handoffs")
            handoffs = int(cur.fetchone()[0])
            recent = []
            cur.execute("""
                SELECT ticker, lead_type, status, evidence_quality_score, suspicious_action,
                       complete_ticket, updated_at, title
                FROM alpha_leads
                ORDER BY updated_at DESC, evidence_quality_score DESC
                LIMIT 12
            """)
            for row in cur.fetchall():
                recent.append({
                    'ticker': row[0], 'lead_type': row[1], 'status': row[2],
                    'evidence_quality_score': float(row[3] or 0), 'suspicious_action': row[4],
                    'complete_ticket': bool(row[5]), 'updated_at': row[6].isoformat() if row[6] else None, 'title': row[7],
                })
            queued = []
            cur.execute("""
                SELECT target_agent, task_type, status, priority, title
                FROM alpha_handoffs
                WHERE status != 'completed'
                ORDER BY priority, created_at DESC
                LIMIT 12
            """)
            for row in cur.fetchall():
                queued.append({'target_agent': row[0], 'task_type': row[1], 'status': row[2], 'priority': row[3], 'title': row[4]})
            return {
                'counts': {'alpha_search_reports': reports, 'alpha_leads': leads, 'alpha_lead_evidence': evidence, 'alpha_handoffs': handoffs},
                'recent_leads': recent,
                'open_handoffs': queued,
                'required_sections': REQUIRED_SECTIONS,
            }
    ensure_alpha_tables(db_path)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        counts = {
            name: con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            for name in ["alpha_search_reports", "alpha_leads", "alpha_lead_evidence", "alpha_handoffs"]
        }
        recent = [dict(r) for r in con.execute(
            """
            SELECT ticker, lead_type, status, evidence_quality_score, suspicious_action,
                   complete_ticket, updated_at, title
            FROM alpha_leads
            ORDER BY updated_at DESC, evidence_quality_score DESC
            LIMIT 12
            """
        ).fetchall()]
        queued = [dict(r) for r in con.execute(
            """
            SELECT target_agent, task_type, status, priority, title
            FROM alpha_handoffs
            WHERE status != 'completed'
            ORDER BY priority, created_at DESC
            LIMIT 12
            """
        ).fetchall()]
        return {"counts": counts, "recent_leads": recent, "open_handoffs": queued, "required_sections": REQUIRED_SECTIONS}
    finally:
        con.close()


def print_template() -> None:
    template = {
        "report": {
            "source_job_id": "wolfy-alpha-search-report",
            "agent_run_id": "$AGENT_RUN_ID if alpha_search_context printed one",
            "title": "Wolfy Alpha Search Report YYYY-MM-DD",
            "summary": "Lead-generation summary. No final trade recommendations unless complete_ticket is true.",
            "market_context": "Brief regime/context.",
            "sections": {section: "Fill this section" for section in REQUIRED_SECTIONS},
        },
        "leads": [
            {
                "ticker": "EXAMPLE",
                "lead_type": "insider_buying|filing_catalyst|news_catalyst|social_scanner|scanner_breakout|deep_research",
                "title": "Short lead title",
                "thesis": "Why this might be alpha, stated as a hypothesis not a trade call.",
                "status": "needs_research",
                "catalyst_window": "date/window or unknown",
                "filing_context": "SEC filing/news context with uncertainty labels",
                "insider_context": "Form 4 open-market-buy context, if any",
                "social_context": "Public chatter summary; flag bot/promo risk if present",
                "next_research_question": "The next concrete question before this can become a trade ticket.",
                "complete_ticket": False,
                "evidence": [
                    {
                        "evidence_type": "sec_filing|press_release|news|scanner|social|insider_form4",
                        "source_title": "Source title",
                        "source_url": "https://...",
                        "quote_or_fact": "Specific sourced fact, not vague vibes.",
                        "quality_score": 0.8,
                        "relevance_score": 0.8,
                    }
                ],
                "suspicious_activity": {"recommended_action": "clear|caution|downgrade|veto", "flags": []},
                "handoffs": [
                    {"target_agent": "Sentinel", "task_type": "alpha_risk_review", "question": "What can invalidate or veto this lead?", "priority": 30},
                    {"target_agent": "Yang", "task_type": "alpha_technical_review", "question": "What chart levels would matter if fundamentals survive?", "priority": 40},
                ],
            }
        ],
    }
    print(json.dumps(template, indent=2))


def _read_payload(path: str) -> Mapping[str, Any]:
    text = Path(path).read_text() if path != "-" else __import__("sys").stdin.read()
    data = json.loads(text)
    if not isinstance(data, Mapping):
        raise SystemExit("payload must be a JSON object")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Store and inspect Wolfy Alpha Search Report leads")
    sub = parser.add_subparsers(dest="cmd")
    p_init = sub.add_parser("init")
    p_init.add_argument("--db", default=str(DEFAULT_DB))
    p_status = sub.add_parser("status")
    p_status.add_argument("--db", default=str(DEFAULT_DB))
    p_template = sub.add_parser("template")
    p_record = sub.add_parser("record")
    p_record.add_argument("--db", default=str(DEFAULT_DB))
    p_record.add_argument("--json", required=True, help="Path to JSON payload, or - for stdin")
    p_record.add_argument("--no-postgres-tasks", action="store_true")
    args = parser.parse_args()

    if args.cmd is None:
        # Cron-agent prompts sometimes ask for a quick pipeline check and omit
        # the subcommand. Treat that as a non-mutating status smoke instead of
        # failing with argparse usage noise in the operations logs.
        print(json.dumps(status_snapshot(DEFAULT_DB), indent=2, sort_keys=True))
    elif args.cmd == "init":
        ensure_alpha_tables(args.db)
        print(f"alpha_search_pipeline initialized db={args.db}")
    elif args.cmd == "status":
        print(json.dumps(status_snapshot(args.db), indent=2, sort_keys=True))
    elif args.cmd == "template":
        print_template()
    elif args.cmd == "record":
        result = record_alpha_payload(_read_payload(args.json), db_path=args.db, create_postgres_tasks=not args.no_postgres_tasks)
        print(json.dumps(result.__dict__, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
