#!/usr/bin/env python3
"""Wolfy recommendation logger and trade-ticket validator.

This helper inserts candidate ideas into the SQLite recommendations table.
Complete, policy-compliant trade tickets are stored as status='pending_review'
only; incomplete or policy-risky ideas are downgraded to status='watching'
(watchlist-only) with validation notes captured as JSON.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from suspicious_activity import (
    ensure_suspicious_activity_tables,
    evaluate_recommendation_suspicion,
    persist_suspicious_flags,
)

BASE = Path("/root/.hermes/wolfy")
DEFAULT_DB = BASE / "wolfy.db"

RECOMMENDATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS recommendations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  report_id INTEGER REFERENCES reports(id),
  timestamp TEXT NOT NULL DEFAULT (datetime('now')),
  ticker TEXT NOT NULL,
  action TEXT NOT NULL,
  recommendation_type TEXT NOT NULL,
  thesis TEXT,
  setup_type TEXT,
  entry_zone TEXT,
  entry_trigger TEXT,
  stop TEXT,
  target TEXT,
  risk_reward TEXT,
  confidence TEXT,
  position_size_suggestion TEXT,
  holding_period TEXT,
  status TEXT NOT NULL DEFAULT 'watching',
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_recs_ticker ON recommendations(ticker);
CREATE INDEX IF NOT EXISTS idx_recs_status ON recommendations(status);
"""

REQUIRED_FIELDS = [
    "ticker",
    "action",
    "instrument_type",
    "robinhood_assumption",
    "thesis",
    "setup",
    "entry_trigger",
    "stop_invalidation",
    "target_exit",
    "risk_reward",
    "confidence",
    "size_guidance",
    "holding_period",
    "risk_notes",
    "jonah_refs",
]

ALIASES = {
    "instrument_type": ("instrument_type", "instrument", "type", "recommendation_type"),
    "robinhood_assumption": ("robinhood_assumption", "robinhood_tradable", "robinhood", "tradability"),
    "setup": ("setup", "setup_type"),
    "entry_trigger": ("entry_trigger", "entry", "trigger", "entry_zone"),
    "stop_invalidation": ("stop_invalidation", "stop", "invalidation"),
    "target_exit": ("target_exit", "target", "exit", "target_or_exit"),
    "size_guidance": ("size_guidance", "position_size_suggestion", "position_size", "sizing"),
    "jonah_refs": ("jonah_refs", "linked_jonah_refs", "linked_refs", "rule_refs", "note_refs"),
}

LONG_ONLY_ACTIONS = {
    "buy",
    "long",
    "watch",
    "add_to_watchlist",
    "call",
    "calls",
    "buy_call",
    "buy_calls",
    "call_option",
    "option_call",
    "debit_call_spread",
    "hold",
}

FORBIDDEN_ACTION_TOKENS = ("short", "sell short", "put", "inverse", "bearish")
FOREIGN_RISK_TERMS = (
    "adr",
    "foreign",
    "china",
    "chinese",
    "russia",
    "russian",
    "government-interference",
    "government interference",
    "manipulation risk",
    "pump-and-dump",
    "pump and dump",
)


def ensure_recommendations_table(db_path: str | Path = DEFAULT_DB) -> None:
    """Create the recommendations table/indexes when running against a fresh temp DB."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        con.executescript(RECOMMENDATIONS_SCHEMA)
        con.commit()
    finally:
        con.close()
    ensure_suspicious_activity_tables(db_path)


def _clean_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value).strip()


def _get(idea: Mapping[str, Any], canonical: str) -> Any:
    for key in ALIASES.get(canonical, (canonical,)):
        if key in idea:
            return idea[key]
    return idea.get(canonical)


def _normalize_jonah_refs(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in re.split(r"[,\n;]+", value) if p.strip()]
        return parts
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _normalized_ticket(idea: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "report_id": idea.get("report_id"),
        "ticker": _clean_string(idea.get("ticker")).upper(),
        "action": _clean_string(idea.get("action")).lower(),
        "instrument_type": _clean_string(_get(idea, "instrument_type")).lower(),
        "robinhood_assumption": _clean_string(_get(idea, "robinhood_assumption")),
        "thesis": _clean_string(idea.get("thesis")),
        "setup": _clean_string(_get(idea, "setup")),
        "entry_trigger": _clean_string(_get(idea, "entry_trigger")),
        "stop_invalidation": _clean_string(_get(idea, "stop_invalidation")),
        "target_exit": _clean_string(_get(idea, "target_exit")),
        "risk_reward": _clean_string(idea.get("risk_reward")),
        "confidence": _clean_string(idea.get("confidence")),
        "size_guidance": _clean_string(_get(idea, "size_guidance")),
        "holding_period": _clean_string(idea.get("holding_period")),
        "risk_notes": _clean_string(idea.get("risk_notes")),
        "jonah_refs": _normalize_jonah_refs(_get(idea, "jonah_refs")),
        "entry_zone": _clean_string(idea.get("entry_zone")),
    }


def validate_ticket(idea: Mapping[str, Any]) -> dict[str, Any]:
    """Return normalized ticket plus validation outcome.

    Complete, long-only, Robinhood-assumed U.S. ideas become actionable.
    Missing fields or user-policy risk flags force watchlist-only status.
    """
    ticket = _normalized_ticket(idea)
    if not ticket["ticker"]:
        raise ValueError("ticker is required to insert any recommendation/watchlist row")

    missing = [field for field in REQUIRED_FIELDS if not ticket[field]]
    risk_flags: list[str] = []

    action = ticket["action"]
    action_words = f" {action} "
    if action and (action not in LONG_ONLY_ACTIONS or any(token in action_words or token in action for token in FORBIDDEN_ACTION_TOKENS)):
        risk_flags.append("action must be long-only")

    tradability_blob = " ".join(
        [ticket["ticker"], ticket["instrument_type"], ticket["robinhood_assumption"], ticket["risk_notes"]]
    ).lower()
    if any(term in tradability_blob for term in FOREIGN_RISK_TERMS):
        risk_flags.append("foreign/manipulation/government-interference risk")

    rh = ticket["robinhood_assumption"].lower()
    if rh and any(term in rh for term in ("not robinhood", "unavailable", "not tradable", "unknown")):
        risk_flags.append("Robinhood tradability not affirmatively assumed")

    actionable = not missing and not risk_flags
    status = "pending_review" if actionable else "watching"
    classification = "actionable_pending_review" if actionable else "watchlist_only"
    return {
        "ticket": ticket,
        "missing_fields": missing,
        "risk_flags": risk_flags,
        "actionable": actionable,
        "status": status,
        "classification": classification,
    }


def log_recommendation(db_path: str | Path, idea: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and insert a recommendation/watchlist row into SQLite."""
    ensure_recommendations_table(db_path)
    validation = validate_ticket(idea)
    suspicious = evaluate_recommendation_suspicion(idea)
    if suspicious["recommended_action"] in {"veto", "downgrade"}:
        validation["actionable"] = False
        validation["status"] = "watching"
        validation["classification"] = "watchlist_only"
        validation["risk_flags"] = list(validation["risk_flags"]) + [f"suspicious activity {suspicious['recommended_action']}"]
    ticket = validation["ticket"]
    if suspicious["recommended_action"] in {"veto", "downgrade"} and ticket["confidence"]:
        ticket["confidence"] = f"reduced from {ticket['confidence']} ({suspicious['recommended_action']}: suspicious activity)"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    notes = {
        "validator": "recommendation_logger.py",
        "validated_at": now,
        "actionable": validation["actionable"],
        "classification": validation["classification"],
        "missing_fields": validation["missing_fields"],
        "risk_flags": validation["risk_flags"],
        "robinhood_assumption": ticket["robinhood_assumption"],
        "risk_notes": ticket["risk_notes"],
        "suspicious_activity": suspicious,
        "jonah_refs": ticket["jonah_refs"],
        "raw_extra": {
            key: value
            for key, value in idea.items()
            if key not in set(REQUIRED_FIELDS) | {"report_id", "entry_zone"} | {alias for aliases in ALIASES.values() for alias in aliases}
        },
    }

    con = sqlite3.connect(db_path)
    try:
        cur = con.execute(
            """
            INSERT INTO recommendations(
                report_id, timestamp, ticker, action, recommendation_type,
                thesis, setup_type, entry_zone, entry_trigger, stop, target,
                risk_reward, confidence, position_size_suggestion,
                holding_period, status, notes
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                ticket["report_id"],
                now,
                ticket["ticker"],
                ticket["action"] or "watch",
                ticket["instrument_type"] or "watchlist",
                ticket["thesis"],
                ticket["setup"],
                ticket["entry_zone"],
                ticket["entry_trigger"],
                ticket["stop_invalidation"],
                ticket["target_exit"],
                ticket["risk_reward"],
                ticket["confidence"],
                ticket["size_guidance"],
                ticket["holding_period"],
                validation["status"],
                json.dumps(notes, sort_keys=True),
            ),
        )
        con.commit()
    finally:
        con.close()

    if suspicious["flags"]:
        persist_suspicious_flags(db_path, "recommendations", str(cur.lastrowid), ticket["ticker"], suspicious)

    return {
        "recommendation_id": cur.lastrowid,
        "ticker": ticket["ticker"],
        "status": validation["status"],
        "classification": validation["classification"],
        "missing_fields": validation["missing_fields"],
        "risk_flags": validation["risk_flags"],
    }


def _load_idea(args: argparse.Namespace) -> dict[str, Any]:
    if args.json_file:
        text = Path(args.json_file).read_text()
    else:
        text = sys.stdin.read()
    if not text.strip():
        raise SystemExit("Provide a JSON idea via --json-file or stdin")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise SystemExit("JSON idea must be an object")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and log a Wolfy recommendation idea.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path; default: /root/.hermes/wolfy/wolfy.db")
    parser.add_argument("--json-file", help="Path to a JSON object describing the idea; stdin is used when omitted")
    parser.add_argument("--validate-only", action="store_true", help="Validate without inserting")
    args = parser.parse_args(argv)

    idea = _load_idea(args)
    if args.validate_only:
        result = validate_ticket(idea)
        result.pop("ticket", None)
    else:
        result = log_recommendation(args.db, idea)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
