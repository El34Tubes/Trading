#!/usr/bin/env python3
"""Deterministic Wolfy alpha-lead promotion gate.

This helper is intentionally conservative.  It reads scanner/alpha/Yang/context rows,
builds a complete trade-ticket candidate only when every policy gate is satisfied,
and calls recommendation_logger only for complete pending_review ideas.  Incomplete
or vetoed leads are marked watch_only with validation notes; dry runs never write.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from recommendation_logger import DEFAULT_DB, log_recommendation, validate_ticket

FRESHNESS_DAYS = 5
WATCH_ONLY_STATUS = "watch_only"
CONVERTED_STATUS = "converted_to_recommendation"

FOREIGN_OR_MANIPULATION_TERMS = (
    "adr",
    "china",
    "chinese",
    "russia",
    "russian",
    "offshore",
    "vie",
    "opaque",
    "government interference",
    "government-interference",
    "pump-and-dump",
    "pump and dump",
    "paid promotion",
    "paid influencer",
    "bot-like",
    "bot like",
)

PRICE_ONLY_TERMS = (
    "scanner",
    "momentum",
    "breakout",
    "relative strength",
    "rsi",
    "price action",
    "technical",
)

NON_PRICE_EVIDENCE_TYPES = {"filing", "insider", "catalyst", "fundamental", "news", "social", "earnings", "knowledge"}


def _connect(db_path: str | Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _json_loads(text: Any, default: Any) -> Any:
    if text is None or text == "":
        return default
    if isinstance(text, (dict, list)):
        return text
    try:
        return json.loads(str(text))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _as_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return datetime.combine(date.fromisoformat(text), datetime.min.time(), tzinfo=timezone.utc)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _days_old(value: str | None, as_of: datetime) -> float | None:
    parsed = _as_utc(value)
    if parsed is None:
        return None
    return (as_of - parsed).total_seconds() / 86400


def _text_blob(*parts: Any) -> str:
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, Mapping):
            chunks.append(json.dumps(part, sort_keys=True))
        elif isinstance(part, (list, tuple, set)):
            chunks.append(" ".join(str(p) for p in part))
        elif part is not None:
            chunks.append(str(part))
    return " ".join(chunks).lower()


def _fetch_leads(con: sqlite3.Connection, limit: int | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT * FROM alpha_leads
        WHERE recommendation_id IS NULL
          AND COALESCE(status, 'new') NOT IN ('converted_to_recommendation', 'rejected')
        ORDER BY evidence_quality_score DESC, updated_at DESC, id ASC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [dict(r) for r in con.execute(sql).fetchall()]


def _latest_scanner(con: sqlite3.Connection, ticker: str) -> dict[str, Any] | None:
    row = con.execute(
        """
        SELECT sr.*, r.run_time, r.data_source, r.universe
        FROM scanner_results sr
        LEFT JOIN scanner_runs r ON r.id = sr.run_id
        WHERE UPPER(sr.ticker)=UPPER(?)
        ORDER BY COALESCE(sr.data_date, r.run_time, sr.created_at) DESC, sr.id DESC
        LIMIT 1
        """,
        (ticker,),
    ).fetchone()
    return _dict(row)


def _evidence(con: sqlite3.Connection, lead_id: int) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT * FROM alpha_lead_evidence
        WHERE lead_id=?
        ORDER BY quality_score DESC, relevance_score DESC, id ASC
        """,
        (lead_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _latest_yang(con: sqlite3.Connection, lead: Mapping[str, Any]) -> dict[str, Any] | None:
    # Prefer explicit alpha lead linkage; fall back to ticker in case older Yang rows lack it.
    row = con.execute(
        """
        SELECT * FROM yang_reviews
        WHERE alpha_lead_id=? OR (alpha_lead_id IS NULL AND UPPER(ticker)=UPPER(?))
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (lead.get("id"), lead.get("ticker")),
    ).fetchone()
    return _dict(row)


def _strategy_refs(con: sqlite3.Connection, limit: int = 3) -> list[str]:
    refs: list[str] = []
    try:
        for row in con.execute(
            "SELECT id, COALESCE(rule, rationale, '') AS text FROM strategy_rules WHERE COALESCE(status,'active')='active' ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall():
            if row["text"]:
                refs.append(f"strategy_rules:{row['id']}:{str(row['text'])[:80]}")
    except sqlite3.Error:
        pass
    return refs


def _knowledge_refs(con: sqlite3.Connection, ticker: str, limit: int = 3) -> list[str]:
    refs: list[str] = []
    try:
        for row in con.execute(
            """
            SELECT id, COALESCE(topic, content, '') AS text FROM knowledge_notes
            WHERE UPPER(COALESCE(topic,'') || ' ' || COALESCE(content,'')) LIKE UPPER(?)
            ORDER BY id DESC LIMIT ?
            """,
            (f"%{ticker}%", limit),
        ).fetchall():
            if row["text"]:
                refs.append(f"knowledge_notes:{row['id']}:{str(row['text'])[:80]}")
    except sqlite3.Error:
        pass
    return refs


def _has_non_price_thesis(lead: Mapping[str, Any], evidence: list[Mapping[str, Any]]) -> bool:
    if any(str(lead.get(field) or "").strip() for field in ("catalyst_window", "filing_context", "insider_context")):
        return True
    for ev in evidence:
        ev_type = str(ev.get("evidence_type") or "").lower()
        if ev_type in NON_PRICE_EVIDENCE_TYPES and ev_type != "scanner":
            return True
    blob = _text_blob(lead.get("title"), lead.get("thesis"), lead.get("social_context"), evidence)
    has_non_price_word = any(term in blob for term in ("filing", "earnings", "margin", "revenue", "backlog", "contract", "fda", "insider", "form 4", "catalyst", "guidance", "cash flow", "free cash flow"))
    price_only = all(term in PRICE_ONLY_TERMS for term in re.findall(r"[a-z]+(?: [a-z]+)?", blob)[:3]) if blob else False
    return has_non_price_word and not price_only


def _rr_text(yang: Mapping[str, Any] | None, payload: Mapping[str, Any]) -> str:
    if yang and yang.get("r_multiple") not in (None, ""):
        return f"{float(yang['r_multiple']):g}R"
    for key in ("risk_reward", "r_multiple", "rr"):
        if payload.get(key) not in (None, ""):
            value = payload[key]
            return f"{float(value):g}R" if isinstance(value, (int, float)) else str(value)
    return ""


def _ticket_from_context(
    con: sqlite3.Connection,
    lead: Mapping[str, Any],
    scanner: Mapping[str, Any] | None,
    evidence: list[Mapping[str, Any]],
    yang: Mapping[str, Any] | None,
) -> dict[str, Any]:
    payload = _json_loads(lead.get("raw_payload_json"), {})
    if not isinstance(payload, Mapping):
        payload = {}
    ticket_payload = payload.get("promotion_ticket") if isinstance(payload.get("promotion_ticket"), Mapping) else payload

    ticker = str(lead.get("ticker") or "").upper()
    close = scanner.get("close") if scanner else None
    atr = (yang or {}).get("atr") or (scanner or {}).get("atr")
    entry_trigger = (yang or {}).get("entry_trigger") or ticket_payload.get("entry_trigger") or ticket_payload.get("trigger") or ""
    stop = (yang or {}).get("stop_invalidation") or ticket_payload.get("stop_invalidation") or ticket_payload.get("stop") or ""
    target = (yang or {}).get("target_exit_plan") or ticket_payload.get("target_exit") or ticket_payload.get("target") or ""
    setup = ticket_payload.get("setup") or ticket_payload.get("setup_type") or ""
    if yang:
        setup_parts = [yang.get("technical_status"), yang.get("trend_read"), yang.get("relative_strength_read"), yang.get("volume_read")]
        setup = "; ".join(str(p) for p in setup_parts if p) or setup

    refs = [f"alpha_leads:{lead.get('id')}"]
    refs.extend(f"alpha_lead_evidence:{ev.get('id')}:{str(ev.get('evidence_type') or '')}" for ev in evidence[:5])
    refs.extend(_strategy_refs(con, 2))
    refs.extend(_knowledge_refs(con, ticker, 2))

    risk_notes = "; ".join(
        part
        for part in [
            "Robinhood tradability assumed for U.S.-listed equity/ETF only; verify in Robinhood before any paper entry.",
            "PDT-aware: do not open/close same day unless user approves; max 3 concurrent positions.",
            f"scanner close={close}" if close is not None else "scanner close unavailable",
            f"ATR={atr}" if atr not in (None, "") else "ATR unavailable",
            str(lead.get("suspicious_flags_json") or ""),
            str(lead.get("social_context") or ""),
            str(lead.get("filing_context") or ""),
            str(lead.get("insider_context") or ""),
        ]
        if str(part).strip()
    )

    return {
        "ticker": ticker,
        "action": ticket_payload.get("action") or "buy",
        "instrument_type": ticket_payload.get("instrument_type") or "equity",
        "robinhood_assumption": ticket_payload.get("robinhood_assumption") or "Robinhood-listed U.S. equity/ETF assumed; verify before paper entry",
        "thesis": str(lead.get("thesis") or "").strip(),
        "setup": setup,
        "entry_zone": (yang or {}).get("entry_zone") or ticket_payload.get("entry_zone") or "",
        "entry_trigger": entry_trigger,
        "stop_invalidation": stop,
        "target_exit": target,
        "risk_reward": _rr_text(yang, ticket_payload),
        "confidence": ticket_payload.get("confidence") or ("medium" if float(lead.get("evidence_quality_score") or 0) >= 0.75 else "low-medium"),
        "size_guidance": ticket_payload.get("size_guidance") or "Paper $5k account: risk <=0.75% account ($37.50 max loss); keep notional small enough for max 3 positions.",
        "holding_period": ticket_payload.get("holding_period") or "2-6 weeks unless stop/target triggers first",
        "risk_notes": risk_notes,
        "jonah_refs": refs,
        "market_context": dict(scanner or {}),
        "alpha_lead_id": lead.get("id"),
        "lead_type": lead.get("lead_type"),
        "catalyst_window": lead.get("catalyst_window"),
        "social_context": lead.get("social_context"),
        "filing_context": lead.get("filing_context"),
        "insider_context": lead.get("insider_context"),
    }


def _validation_notes(
    lead: Mapping[str, Any],
    scanner: Mapping[str, Any] | None,
    evidence: list[Mapping[str, Any]],
    yang: Mapping[str, Any] | None,
    ticket_validation: Mapping[str, Any],
    as_of: datetime,
    freshness_days: int,
) -> list[str]:
    notes: list[str] = []
    if scanner is None:
        notes.append("fresh scanner data missing")
    else:
        run_age = _days_old(scanner.get("run_time") or scanner.get("created_at"), as_of)
        data_age = _days_old(scanner.get("data_date"), as_of)
        if (run_age is None or run_age > freshness_days) or (data_age is None or data_age > freshness_days):
            notes.append("scanner data is stale")
        if int(scanner.get("liquidity_pass") or 0) != 1:
            notes.append("liquidity gate failed")
    if not _has_non_price_thesis(lead, evidence):
        notes.append("non-price thesis/catalyst missing")
    if yang is None or not all(str((yang or {}).get(k) or "").strip() for k in ("entry_trigger", "stop_invalidation", "target_exit_plan")):
        notes.append("technical setup/trigger missing")
    if not str((yang or {}).get("r_multiple") or "").strip():
        notes.append("risk/reward missing")
    suspicious_action = str(lead.get("suspicious_action") or "clear").lower()
    flags = _json_loads(lead.get("suspicious_flags_json"), [])
    flag_blob = _text_blob(flags, ticket_validation.get("risk_flags"), lead.get("filing_context"), lead.get("thesis"))
    severe_flag = any(
        isinstance(flag, Mapping)
        and str(flag.get("severity") or "").lower() in {"high", "critical"}
        for flag in (flags if isinstance(flags, list) else [])
    )
    foreign_or_government_risk = any(term in flag_blob for term in ("adr", "china", "chinese", "russia", "russian", "offshore", "vie", "opaque", "government interference", "government-interference"))
    if suspicious_action in {"veto", "downgrade"} or severe_flag or foreign_or_government_risk:
        notes.append("manipulation/foreign/government-interference veto")
    for field in ticket_validation.get("missing_fields", []):
        notes.append(f"recommendation ticket missing {field}")
    for flag in ticket_validation.get("risk_flags", []):
        if flag not in notes:
            notes.append(str(flag))
    # Preserve order but remove duplicates.
    seen = set()
    deduped = []
    for note in notes:
        if note not in seen:
            seen.add(note)
            deduped.append(note)
    return deduped


def _mark_watch_only(con: sqlite3.Connection, lead_id: int, notes: list[str]) -> None:
    con.execute(
        """
        UPDATE alpha_leads
        SET status=?,
            complete_ticket=0,
            next_research_question=? ,
            updated_at=datetime('now')
        WHERE id=?
        """,
        (WATCH_ONLY_STATUS, "; ".join(notes), lead_id),
    )


def _mark_converted(con: sqlite3.Connection, lead_id: int, recommendation_id: int) -> None:
    con.execute(
        """
        UPDATE alpha_leads
        SET status=?, complete_ticket=1, recommendation_id=?, updated_at=datetime('now')
        WHERE id=?
        """,
        (CONVERTED_STATUS, recommendation_id, lead_id),
    )


def evaluate_alpha_lead(
    con: sqlite3.Connection,
    lead: Mapping[str, Any],
    *,
    as_of: datetime,
    freshness_days: int = FRESHNESS_DAYS,
) -> dict[str, Any]:
    scanner = _latest_scanner(con, str(lead.get("ticker") or ""))
    ev = _evidence(con, int(lead["id"]))
    yang = _latest_yang(con, lead)
    ticket = _ticket_from_context(con, lead, scanner, ev, yang)
    ticket_validation = validate_ticket(ticket)
    notes = _validation_notes(lead, scanner, ev, yang, ticket_validation, as_of, freshness_days)
    actionable = not notes and bool(ticket_validation.get("actionable"))
    classification = "actionable_pending_review" if actionable else "watchlist_only"
    return {
        "lead_id": lead.get("id"),
        "ticker": str(lead.get("ticker") or "").upper(),
        "classification": classification,
        "target_status": "pending_review" if actionable else WATCH_ONLY_STATUS,
        "would_call_recommendation_logger": actionable,
        "validation_notes": notes,
        "ticket": ticket,
        "scanner_result_id": scanner.get("id") if scanner else None,
        "yang_review_id": yang.get("id") if yang else None,
        "evidence_ids": [e.get("id") for e in ev],
    }


def promote_alpha_leads(
    db_path: str | Path = DEFAULT_DB,
    *,
    dry_run: bool = True,
    as_of: str | datetime | None = None,
    freshness_days: int = FRESHNESS_DAYS,
    limit: int | None = None,
) -> dict[str, Any]:
    """Evaluate alpha leads and optionally promote complete tickets.

    dry_run=True performs no writes and is safe for cron/preflight diagnostics.
    dry_run=False writes only two kinds of changes: complete leads are logged through
    recommendation_logger as pending_review, and incomplete/vetoed leads are marked
    watch_only with validation notes on alpha_leads.next_research_question.
    """
    if isinstance(as_of, datetime):
        as_of_dt = as_of.astimezone(timezone.utc) if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
    elif as_of:
        parsed = _as_utc(str(as_of))
        if parsed is None:
            raise ValueError(f"Invalid as_of timestamp: {as_of}")
        as_of_dt = parsed
    else:
        as_of_dt = datetime.now(timezone.utc)

    con = _connect(db_path)
    decisions: list[dict[str, Any]] = []
    live_writes = 0
    try:
        leads = _fetch_leads(con, limit)
        for lead in leads:
            decision = evaluate_alpha_lead(con, lead, as_of=as_of_dt, freshness_days=freshness_days)
            if decision["would_call_recommendation_logger"]:
                if not dry_run:
                    logged = log_recommendation(db_path, decision["ticket"])
                    decision["recommendation_id"] = logged["recommendation_id"]
                    decision["logged_status"] = logged["status"]
                    _mark_converted(con, int(lead["id"]), int(logged["recommendation_id"]))
                    live_writes += 1
                else:
                    decision["recommendation_id"] = None
            else:
                decision["recommendation_id"] = None
                if not dry_run:
                    _mark_watch_only(con, int(lead["id"]), decision["validation_notes"])
                    live_writes += 1
            decisions.append({k: v for k, v in decision.items() if k != "ticket"})
        if not dry_run:
            con.commit()
    finally:
        con.close()

    summary = {
        "evaluated": len(decisions),
        "pending_review": sum(1 for d in decisions if d["classification"] == "actionable_pending_review"),
        "watch_only": sum(1 for d in decisions if d["classification"] == "watchlist_only"),
        "live_writes": live_writes,
        "dry_run": dry_run,
    }
    return {"summary": summary, "decisions": decisions}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Promote complete Wolfy alpha leads to recommendation tickets; defaults to dry run.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    parser.add_argument("--live-write", action="store_true", help="Actually write converted/watch_only statuses; omitted means dry-run")
    parser.add_argument("--as-of", help="Evaluation timestamp, ISO-8601; defaults to now UTC")
    parser.add_argument("--freshness-days", type=int, default=FRESHNESS_DAYS, help="Maximum scanner age in days")
    parser.add_argument("--limit", type=int, help="Maximum alpha leads to evaluate")
    args = parser.parse_args(argv)

    result = promote_alpha_leads(
        args.db,
        dry_run=not args.live_write,
        as_of=args.as_of,
        freshness_days=args.freshness_days,
        limit=args.limit,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
