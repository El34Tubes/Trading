import json
import sqlite3
from pathlib import Path

from alpha_search_pipeline import (
    REQUIRED_SECTIONS,
    ensure_alpha_tables,
    evidence_quality,
    record_alpha_payload,
    status_snapshot,
)


def sample_payload():
    return {
        "report": {
            "source_job_id": "pytest-alpha",
            "agent_run_id": "123",
            "title": "Pytest Alpha Search Report",
            "summary": "Stored leads for smoke testing.",
            "market_context": "test regime",
            "sections": {section: f"{section} section" for section in REQUIRED_SECTIONS},
        },
        "leads": [
            {
                "ticker": "ABC",
                "lead_type": "filing_catalyst",
                "title": "ABC filing catalyst",
                "thesis": "ABC may have a real catalyst, but needs risk review before any trade ticket.",
                "status": "needs_research",
                "filing_context": "8-K filed with product update.",
                "social_context": "Quiet public chatter.",
                "next_research_question": "Does the filing materially change forward estimates?",
                "evidence": [
                    {
                        "evidence_type": "sec_filing",
                        "source_title": "ABC 8-K",
                        "source_url": "https://www.sec.gov/example",
                        "quote_or_fact": "Company filed an 8-K describing a new customer launch.",
                        "quality_score": 0.9,
                        "relevance_score": 0.85,
                    },
                    {
                        "evidence_type": "scanner",
                        "source_title": "Wolfy scanner",
                        "quote_or_fact": "ABC passed liquidity screen with positive 20-day relative strength.",
                        "quality_score": 0.65,
                        "relevance_score": 0.7,
                    },
                ],
                "suspicious_activity": {"recommended_action": "clear", "flags": []},
                "handoffs": [
                    {
                        "target_agent": "Sentinel",
                        "task_type": "alpha_risk_review",
                        "question": "Find reasons ABC should be rejected.",
                        "priority": 30,
                    },
                    {
                        "target_agent": "Yang",
                        "task_type": "alpha_technical_review",
                        "question": "Identify trigger/stop levels only if ABC survives risk review.",
                        "priority": 40,
                    },
                ],
            }
        ],
    }


def test_record_alpha_payload_persists_report_lead_evidence_and_handoffs(tmp_path):
    db = tmp_path / "wolfy.db"
    result = record_alpha_payload(sample_payload(), db_path=db, create_postgres_tasks=False)

    assert result.report_id == 1
    assert result.leads_seen == 1
    assert result.leads_upserted == 1
    assert result.evidence_rows_seen == 2
    assert result.handoffs_seen == 2

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    lead = con.execute("SELECT * FROM alpha_leads WHERE ticker='ABC'").fetchone()
    assert lead is not None
    assert lead["status"] == "needs_research"
    assert lead["complete_ticket"] == 0
    assert lead["evidence_quality_score"] > 0.7
    assert lead["suspicious_action"] == "clear"
    assert json.loads(lead["suspicious_flags_json"]) == []
    assert con.execute("SELECT COUNT(*) FROM alpha_lead_evidence WHERE lead_id=?", (lead["id"],)).fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM alpha_handoffs WHERE lead_id=?", (lead["id"],)).fetchone()[0] == 2
    con.close()


def test_record_alpha_payload_is_idempotent_by_source_fingerprint(tmp_path):
    db = tmp_path / "wolfy.db"
    payload = sample_payload()
    first = record_alpha_payload(payload, db_path=db, create_postgres_tasks=False)
    second = record_alpha_payload(payload, db_path=db, create_postgres_tasks=False)
    assert first.leads_upserted == 1
    assert second.leads_upserted == 1

    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM alpha_leads").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM alpha_lead_evidence").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM alpha_handoffs").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM alpha_search_reports").fetchone()[0] == 2
    con.close()


def test_status_snapshot_reports_required_sections_and_recent_leads(tmp_path):
    db = tmp_path / "wolfy.db"
    ensure_alpha_tables(db)
    record_alpha_payload(sample_payload(), db_path=db, create_postgres_tasks=False)
    snap = status_snapshot(db)
    assert snap["counts"]["alpha_leads"] == 1
    assert "insider_buying" in snap["required_sections"]
    assert snap["recent_leads"][0]["ticker"] == "ABC"


def test_evidence_quality_rewards_multiple_relevant_sourced_items():
    score, count, max_q = evidence_quality(sample_payload()["leads"][0]["evidence"])
    assert count == 2
    assert score > 0.7
    assert max_q == 0.9
