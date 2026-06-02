#!/usr/bin/env python3
"""Persistence helpers for Yang technical-analysis reviews.

Yang is deliberately downstream of Wolfy. These helpers make that boundary
explicit: Yang can persist entry/exit/invalidation work only for an existing
Wolfy recommendation with a non-empty alpha thesis, optionally linked to an
alpha lead. Yang must not originate alpha by reviewing scanner rows alone.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

DEFAULT_DB = Path("/root/.hermes/wolfy/wolfy.db")

YANG_REVIEWS_SCHEMA = """
CREATE TABLE IF NOT EXISTS yang_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  recommendation_id INTEGER NOT NULL REFERENCES recommendations(id) ON DELETE CASCADE,
  alpha_lead_id INTEGER REFERENCES alpha_leads(id) ON DELETE SET NULL,
  ticker TEXT NOT NULL,
  wolfy_alpha_thesis TEXT NOT NULL,
  technical_status TEXT NOT NULL,
  entry_trigger TEXT NOT NULL,
  entry_zone TEXT,
  stop_invalidation TEXT NOT NULL,
  target_exit_plan TEXT NOT NULL,
  atr REAL,
  r_multiple REAL,
  trend_read TEXT,
  relative_strength_read TEXT,
  volume_read TEXT,
  notes TEXT,
  raw_payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_yang_reviews_rec_created ON yang_reviews(recommendation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_yang_reviews_ticker_created ON yang_reviews(ticker, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_yang_reviews_status ON yang_reviews(technical_status, created_at DESC);
"""

ELIGIBLE_RECOMMENDATION_STATUSES = {
    "approved",
    "pending_review",
    "needs_yang",
    "alpha_candidate",
    "candidate",
}

REQUIRED_REVIEW_FIELDS = [
    "recommendation_id",
    "ticker",
    "wolfy_alpha_thesis",
    "technical_status",
    "entry_trigger",
    "stop_invalidation",
    "target_exit_plan",
]


def ensure_yang_review_tables(db_path: str | Path = DEFAULT_DB) -> None:
    """Install Yang's non-destructive SQLite persistence table and indexes."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.executescript(YANG_REVIEWS_SCHEMA)
        con.commit()
    finally:
        con.close()


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"expected numeric value, got {value!r}") from exc


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _best_alpha_lead_for_recommendation(con: sqlite3.Connection, rec: sqlite3.Row) -> sqlite3.Row | None:
    """Return the strongest alpha lead linked to the recommendation, if any.

    Prefer an explicit alpha_leads.recommendation_id link. Fall back to a recent
    same-ticker lead with evidence and a non-empty thesis so older Wolfy records
    can still get context without fabricating a link.
    """
    alpha = con.execute(
        """
        SELECT * FROM alpha_leads
        WHERE recommendation_id=? AND trim(COALESCE(thesis,'')) <> ''
        ORDER BY evidence_quality_score DESC, evidence_count DESC, updated_at DESC, id DESC
        LIMIT 1
        """,
        (rec["id"],),
    ).fetchone()
    if alpha is not None:
        return alpha
    return con.execute(
        """
        SELECT * FROM alpha_leads
        WHERE upper(ticker)=upper(?)
          AND trim(COALESCE(thesis,'')) <> ''
          AND COALESCE(suspicious_action,'clear') NOT IN ('veto')
        ORDER BY complete_ticket DESC, evidence_quality_score DESC, evidence_count DESC, updated_at DESC, id DESC
        LIMIT 1
        """,
        (rec["ticker"],),
    ).fetchone()


def eligible_yang_candidates(db_path: str | Path = DEFAULT_DB, limit: int = 12) -> list[dict[str, Any]]:
    """Return Wolfy recommendations Yang may review.

    Eligibility requires an existing recommendation row in a reviewable status
    and a non-empty Wolfy thesis. Scanner-only rows and thesis-free watchlist
    ideas are deliberately excluded so Yang cannot originate alpha.
    """
    ensure_yang_review_tables(db_path)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            f"""
            SELECT * FROM recommendations
            WHERE lower(status) IN ({','.join('?' for _ in ELIGIBLE_RECOMMENDATION_STATUSES)})
              AND trim(COALESCE(thesis,'')) <> ''
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
            """,
            (*sorted(ELIGIBLE_RECOMMENDATION_STATUSES), int(limit)),
        ).fetchall()
        candidates: list[dict[str, Any]] = []
        for rec in rows:
            alpha = _best_alpha_lead_for_recommendation(con, rec)
            candidates.append(
                {
                    "recommendation_id": rec["id"],
                    "alpha_lead_id": alpha["id"] if alpha is not None else None,
                    "ticker": rec["ticker"],
                    "status": rec["status"],
                    "action": rec["action"],
                    "recommendation_type": rec["recommendation_type"],
                    "wolfy_alpha_thesis": rec["thesis"],
                    "alpha_lead_thesis": alpha["thesis"] if alpha is not None else None,
                    "alpha_lead_title": alpha["title"] if alpha is not None else None,
                    "alpha_evidence_quality_score": alpha["evidence_quality_score"] if alpha is not None else None,
                    "setup_type": rec["setup_type"],
                    "entry_zone": rec["entry_zone"],
                    "entry_trigger": rec["entry_trigger"],
                    "stop": rec["stop"],
                    "target": rec["target"],
                    "risk_reward": rec["risk_reward"],
                    "confidence": rec["confidence"],
                    "position_size_suggestion": rec["position_size_suggestion"],
                    "holding_period": rec["holding_period"],
                    "notes": rec["notes"],
                }
            )
        return candidates
    finally:
        con.close()


def persist_yang_review(db_path: str | Path, review: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and insert a Yang review row.

    The validation intentionally demands ``wolfy_alpha_thesis``. If the current
    job lacks a Wolfy thesis, Yang should report no technical action rather than
    inventing a trade setup from price action alone.
    """
    ensure_yang_review_tables(db_path)
    normalized = {
        "recommendation_id": review.get("recommendation_id"),
        "alpha_lead_id": review.get("alpha_lead_id"),
        "ticker": _clean(review.get("ticker")).upper(),
        "wolfy_alpha_thesis": _clean(review.get("wolfy_alpha_thesis")),
        "technical_status": _clean(review.get("technical_status") or review.get("status")).lower(),
        "entry_trigger": _clean(review.get("entry_trigger")),
        "entry_zone": _clean(review.get("entry_zone")),
        "stop_invalidation": _clean(review.get("stop_invalidation") or review.get("stop")),
        "target_exit_plan": _clean(review.get("target_exit_plan") or review.get("target")),
        "atr": _float_or_none(review.get("atr")),
        "r_multiple": _float_or_none(review.get("r_multiple")),
        "trend_read": _clean(review.get("trend_read")),
        "relative_strength_read": _clean(review.get("relative_strength_read")),
        "volume_read": _clean(review.get("volume_read")),
        "notes": _clean(review.get("notes")),
    }
    missing = [field for field in REQUIRED_REVIEW_FIELDS if not normalized.get(field)]
    if missing:
        raise ValueError(f"missing required Yang review field(s): {', '.join(missing)}")

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        rec = _row_to_dict(
            con.execute(
                "SELECT id, ticker, thesis FROM recommendations WHERE id=?",
                (normalized["recommendation_id"],),
            ).fetchone()
        )
        if rec is None:
            raise ValueError(f"recommendation_id {normalized['recommendation_id']} does not exist")
        if not _clean(rec.get("thesis")):
            raise ValueError("recommendation lacks wolfy_alpha_thesis; Yang cannot persist a technical plan")
        if rec["ticker"].upper() != normalized["ticker"]:
            raise ValueError("review ticker does not match recommendation ticker")

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        raw = dict(review)
        raw.setdefault("persisted_at", now)
        cur = con.execute(
            """
            INSERT INTO yang_reviews(
              created_at, recommendation_id, alpha_lead_id, ticker, wolfy_alpha_thesis,
              technical_status, entry_trigger, entry_zone, stop_invalidation,
              target_exit_plan, atr, r_multiple, trend_read, relative_strength_read,
              volume_read, notes, raw_payload_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                now,
                normalized["recommendation_id"],
                normalized["alpha_lead_id"],
                normalized["ticker"],
                normalized["wolfy_alpha_thesis"],
                normalized["technical_status"],
                normalized["entry_trigger"],
                normalized["entry_zone"],
                normalized["stop_invalidation"],
                normalized["target_exit_plan"],
                normalized["atr"],
                normalized["r_multiple"],
                normalized["trend_read"],
                normalized["relative_strength_read"],
                normalized["volume_read"],
                normalized["notes"],
                json.dumps(raw, sort_keys=True),
            ),
        )
        con.commit()
        return {
            "review_id": cur.lastrowid,
            "recommendation_id": normalized["recommendation_id"],
            "alpha_lead_id": normalized["alpha_lead_id"],
            "ticker": normalized["ticker"],
            "status": normalized["technical_status"],
        }
    finally:
        con.close()


def _load_json(args: argparse.Namespace) -> dict[str, Any]:
    text = Path(args.json_file).read_text() if args.json_file else sys.stdin.read()
    if not text.strip():
        raise SystemExit("Provide a Yang review JSON object via --json-file or stdin")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise SystemExit("Yang review payload must be a JSON object")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Persist or inspect Yang technical-analysis reviews.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("candidates", help="Print current Yang-eligible Wolfy recommendations")
    persist = sub.add_parser("persist", help="Persist a Yang review JSON payload")
    persist.add_argument("--json-file", help="Review JSON file; stdin is used when omitted")
    args = parser.parse_args(argv)

    if args.command == "candidates":
        print(json.dumps(eligible_yang_candidates(args.db), indent=2, sort_keys=True))
        return 0
    if args.command == "persist":
        print(json.dumps(persist_yang_review(args.db, _load_json(args)), indent=2, sort_keys=True))
        return 0
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
