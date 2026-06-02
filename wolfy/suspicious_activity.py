#!/usr/bin/env python3
"""Wolfy suspicious-activity detection layer.

Flags pump-like, dilution, reverse-split, offshore/opaque, and social-promotion
risks so recommendations/scanner leads are downgraded or vetoed before they can
become actionable trade tickets.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Mapping

DEFAULT_DB = Path("/root/.hermes/wolfy/wolfy.db")

SUSPICIOUS_SCHEMA = """
CREATE TABLE IF NOT EXISTS suspicious_activity_flags (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_table TEXT NOT NULL,
  source_id TEXT,
  ticker TEXT NOT NULL,
  flag_type TEXT NOT NULL,
  severity TEXT NOT NULL,
  recommended_action TEXT NOT NULL,
  evidence TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_suspicious_flags_ticker ON suspicious_activity_flags(ticker, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_suspicious_flags_source ON suspicious_activity_flags(source_table, source_id);
"""


def ensure_suspicious_activity_tables(db_path: str | Path = DEFAULT_DB) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        con.executescript(SUSPICIOUS_SCHEMA)
        con.commit()
    finally:
        con.close()


def _num(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _text_blob(*parts: Any) -> str:
    chunks: list[str] = []
    for p in parts:
        if isinstance(p, Mapping):
            chunks.append(json.dumps(p, sort_keys=True))
        elif isinstance(p, (list, tuple, set)):
            chunks.append(" ".join(str(x) for x in p))
        elif p is not None:
            chunks.append(str(p))
    return " ".join(chunks).lower()


def _flag(flag_type: str, severity: str, evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {"flag_type": flag_type, "severity": severity, "evidence": dict(evidence)}


def _action(flags: list[dict[str, Any]]) -> tuple[str, str, float]:
    severities = {f["severity"] for f in flags}
    types = {f["flag_type"] for f in flags}
    if "critical" in severities or {"low_float_price_spike", "abnormal_volume_without_catalyst"}.issubset(types):
        return "veto", "veto", 0.20
    if "high" in severities:
        return "downgrade", "reduced", 0.50
    if flags:
        return "caution", "slightly_reduced", 0.75
    return "clear", "none", 1.0


def evaluate_scanner_suspicion(ticker: str, row: Mapping[str, Any]) -> dict[str, Any]:
    ticker = str(ticker or row.get("ticker") or "").upper()
    close = _num(row.get("close"))
    r5 = _num(row.get("r5"))
    r20 = _num(row.get("r20"))
    relvol = _num(row.get("relative_volume") or row.get("rel_volume") or row.get("volume_ratio"))
    avg_volume = _num(row.get("avg_volume"))
    float_shares = _num(row.get("float_shares"))
    market_cap = _num(row.get("market_cap"))
    catalyst = bool(row.get("catalyst_confirmed"))
    flags: list[dict[str, Any]] = []

    if (close and close < 10) and ((float_shares and float_shares < 15_000_000) or (market_cap and market_cap < 300_000_000)) and (r5 >= 40 or r20 >= 80):
        flags.append(_flag("low_float_price_spike", "critical", {"ticker": ticker, "close": close, "r5": r5, "r20": r20, "float_shares": float_shares, "market_cap": market_cap}))
    if not catalyst and (relvol >= 8 or (avg_volume and avg_volume < 500_000 and (r5 >= 30 or r20 >= 60))):
        flags.append(_flag("abnormal_volume_without_catalyst", "critical", {"ticker": ticker, "relative_volume": relvol, "avg_volume": avg_volume, "catalyst_confirmed": catalyst}))

    recommended_action, confidence_adjustment, multiplier = _action(flags)
    return {"ticker": ticker, "flags": flags, "recommended_action": recommended_action, "confidence_adjustment": confidence_adjustment, "confidence_multiplier": multiplier}


def evaluate_recommendation_suspicion(idea: Mapping[str, Any]) -> dict[str, Any]:
    ticker = str(idea.get("ticker") or "").upper()
    blob = _text_blob(
        idea,
        idea.get("risk_notes"),
        idea.get("social_context"),
        idea.get("corporate_actions"),
        idea.get("filing_context"),
        idea.get("insider_context"),
        idea.get("thesis"),
    )
    flags: list[dict[str, Any]] = []

    if re.search(r"reverse\s+split|split\s+last|1-for-\d+", blob):
        flags.append(_flag("reverse_split_history", "high", {"ticker": ticker, "matched": "reverse split"}))
    if any(term in blob for term in ["dilution", "atm offering", "offering", "registered direct", "warrant overhang"]):
        flags.append(_flag("dilution_or_offering_history", "high", {"ticker": ticker, "matched": "dilution/offering"}))
    if any(term in blob for term in ["influencer", "discord room", "paid promotion", "paid discord", "viral fintwit", "pile-on", "pile on"]):
        flags.append(_flag("influencer_pile_on", "high", {"ticker": ticker, "matched": "influencer/promotion"}))
    if any(term in blob for term in ["bot-like", "bot like", "cashtag velocity", "bots"]):
        flags.append(_flag("bot_like_cashtag_velocity", "high", {"ticker": ticker, "matched": "bot-like cashtag velocity"}))
    insider_terms = ["insider buy", "insider buying", "form 4", "insiders", "management buy"]
    social_terms = ["social campaign", "paid influencer", "paid promotion", "pile-on", "pile on", "cashtag", "trending", "promotion"]
    timing_terms = ["after", "before", "timing conflict", "timing conflicts", "sold into promotion", "selling into promotion"]
    if any(term in blob for term in insider_terms) and any(term in blob for term in social_terms) and any(term in blob for term in timing_terms):
        flags.append(_flag("insider_social_timing_conflict", "high", {"ticker": ticker, "matched": "insider/social timing conflict"}))
    if any(term in blob for term in ["cayman", "offshore", "vie", "opaque", "china adr", "adr"]):
        flags.append(_flag("offshore_or_opaque_risk", "critical", {"ticker": ticker, "matched": "offshore/opaque"}))

    market = idea.get("market_context") if isinstance(idea.get("market_context"), Mapping) else {}
    if market:
        scanner = evaluate_scanner_suspicion(ticker, {**market, "ticker": ticker})
        flags.extend(scanner["flags"])

    recommended_action, confidence_adjustment, multiplier = _action(flags)
    return {"ticker": ticker, "flags": flags, "recommended_action": recommended_action, "confidence_adjustment": confidence_adjustment, "confidence_multiplier": multiplier}


def persist_suspicious_flags(db_path: str | Path, source_table: str, source_id: str, ticker: str, result: Mapping[str, Any]) -> int:
    ensure_suspicious_activity_tables(db_path)
    con = sqlite3.connect(db_path)
    try:
        inserted = 0
        for f in result.get("flags", []):
            con.execute(
                """
                INSERT INTO suspicious_activity_flags(source_table,source_id,ticker,flag_type,severity,recommended_action,evidence)
                VALUES(?,?,?,?,?,?,?)
                """,
                (source_table, str(source_id), str(ticker).upper(), f["flag_type"], f["severity"], result.get("recommended_action", "caution"), json.dumps(f.get("evidence", {}), sort_keys=True)),
            )
            inserted += 1
        con.commit()
        return inserted
    finally:
        con.close()
