#!/usr/bin/env python3
"""Deterministic Sentinel persistence for pending Wolfy recommendations.

This script reviews SQLite recommendations with status='pending_review', writes
structured rows to Postgres recommendation_reviews, and advances the SQLite
status to approved/rejected/needs_revision. It deliberately handles mechanical
policy/account/risk checks in code; any LLM rationale can be supplied as an
extra note but does not bypass these gates.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

try:
    import psycopg
    from psycopg.types.json import Jsonb
except Exception:  # pragma: no cover - exercised only where psycopg is absent
    psycopg = None
    Jsonb = None

DEFAULT_DB = Path("/root/.hermes/wolfy/wolfy.db")
DEFAULT_PG_DSN = "dbname=wolfy user=root host=/var/run/postgresql"

APPROVED = "approved"
REJECTED = "rejected"
NEEDS_REVISION = "needs_revision"

REQUIRED_SQLITE_FIELDS = [
    "ticker",
    "action",
    "recommendation_type",
    "thesis",
    "setup_type",
    "entry_trigger",
    "stop",
    "target",
    "risk_reward",
    "confidence",
    "position_size_suggestion",
    "holding_period",
]

LONG_ONLY_ACTIONS = {
    "buy",
    "long",
    "call",
    "calls",
    "buy_call",
    "buy_calls",
    "call_option",
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
NEGATED_RISK_PATTERNS = (
    "no foreign",
    "no known foreign",
    "no manipulation",
    "no known manipulation",
    "no foreign/manipulation",
    "no foreign manipulation",
    "no government-interference",
    "no government interference",
)

PGReviewWriter = Callable[[list[dict[str, Any]]], None]


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _load_notes(raw_notes: Any) -> dict[str, Any]:
    text = _clean(raw_notes)
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"raw_notes": text}
    return parsed if isinstance(parsed, dict) else {"raw_notes": parsed}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,;\n]+", value) if part.strip()]
    return [value]


def _parse_rr(value: Any) -> float | None:
    text = _clean(value).lower()
    if not text:
        return None
    # Handles "2.2R", "2:1", "risk/reward 2 to 1" and similar compact forms.
    colon = re.search(r"(\d+(?:\.\d+)?)\s*[:/]\s*1", text)
    if colon:
        return float(colon.group(1))
    to_one = re.search(r"(\d+(?:\.\d+)?)\s*(?:r|to\s*1|x)", text)
    if to_one:
        return float(to_one.group(1))
    number = re.search(r"\d+(?:\.\d+)?", text)
    return float(number.group(0)) if number else None


def _has_unnegated_foreign_risk(blob: str) -> bool:
    """Conservative text gate: risk terms count unless explicitly negated nearby."""
    if not any(term in blob for term in FOREIGN_RISK_TERMS):
        return False
    if any(pattern in blob for pattern in NEGATED_RISK_PATTERNS):
        strong_terms = ("adr", "china", "chinese", "russia", "russian", "pump-and-dump", "pump and dump")
        return any(term in blob for term in strong_terms)
    return True


def _active_position_count(con: sqlite3.Connection) -> int | None:
    table = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='paper_trades'"
    ).fetchone()
    if table is None:
        return None
    cols = {row[1] for row in con.execute("PRAGMA table_info(paper_trades)").fetchall()}
    if "status" not in cols:
        return None
    return int(
        con.execute(
            """
            SELECT COUNT(*) FROM paper_trades
            WHERE lower(COALESCE(status,'')) IN ('open','pending','triggered','active')
            """
        ).fetchone()[0]
    )


def pending_recommendations(db_path: str | Path = DEFAULT_DB, limit: int | None = None) -> list[sqlite3.Row]:
    """Return pending_review recommendations in deterministic FIFO order."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        sql = """
            SELECT * FROM recommendations
            WHERE lower(status) = 'pending_review'
            ORDER BY timestamp ASC, id ASC
        """
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (int(limit),)
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def evaluate_recommendation(row: sqlite3.Row | Mapping[str, Any], active_positions: int | None = None) -> dict[str, Any]:
    """Run deterministic Sentinel checks and return a Postgres review payload."""
    rec = dict(row)
    notes = _load_notes(rec.get("notes"))
    failures: list[str] = []
    revision_items: list[str] = []
    warnings: list[str] = []

    for field in REQUIRED_SQLITE_FIELDS:
        if not _clean(rec.get(field)):
            revision_items.append(f"missing required field: {field}")

    action = _clean(rec.get("action")).lower()
    action_blob = f" {action} "
    if action and (action not in LONG_ONLY_ACTIONS or any(tok in action_blob or tok in action for tok in FORBIDDEN_ACTION_TOKENS)):
        failures.append("action violates long-only/no-shorts/no-puts constraint")

    blob = " ".join(
        _clean(v).lower()
        for v in [
            rec.get("ticker"),
            rec.get("recommendation_type"),
            rec.get("thesis"),
            rec.get("notes"),
            notes.get("risk_notes"),
            notes.get("robinhood_assumption"),
        ]
    )
    if _has_unnegated_foreign_risk(blob):
        failures.append("foreign/manipulation/government-interference risk")

    suspicious = notes.get("suspicious_activity") if isinstance(notes.get("suspicious_activity"), dict) else {}
    suspicious_action = _clean(suspicious.get("recommended_action")).lower()
    if suspicious_action in {"veto", "downgrade"}:
        failures.append(f"suspicious activity {suspicious_action}")
    for flag in _as_list(notes.get("risk_flags")):
        flag_text = _clean(flag)
        if flag_text:
            failures.append(flag_text)

    rh = _clean(notes.get("robinhood_assumption") or notes.get("robinhood_tradable")).lower()
    if not rh:
        revision_items.append("missing Robinhood tradability assumption")
    elif any(term in rh for term in ("not robinhood", "unavailable", "not tradable", "unknown")):
        failures.append("Robinhood tradability not affirmatively assumed")

    if not _clean(rec.get("stop")):
        revision_items.append("stop/invalidation is required")

    rr = _parse_rr(rec.get("risk_reward"))
    if rr is None:
        revision_items.append("risk/reward must be numeric or R-multiple based")
    elif rr < 2.0:
        revision_items.append("risk/reward below 2R minimum for swing candidate")

    sizing = _clean(rec.get("position_size_suggestion")).lower()
    if not sizing:
        revision_items.append("position sizing guidance is required")
    elif not any(token in sizing for token in ("$5k", "$5,000", "5000", "0.", "1%", "<=", "max 3", "one of max 3")):
        revision_items.append("size guidance must reference $5k account, risk cap, or max-3 position constraint")

    hold = _clean(rec.get("holding_period")).lower()
    if any(term in hold for term in ("intraday", "day trade", "same day", "scalp")):
        revision_items.append("holding period creates PDT/day-trade risk")

    jonah_refs = _as_list(notes.get("jonah_refs") or notes.get("linked_jonah_refs"))
    if not jonah_refs:
        revision_items.append("missing Jonah/strategy/knowledge references")

    if active_positions is not None and active_positions >= 3:
        revision_items.append("max 3 concurrent paper positions already reached")
    elif active_positions is None:
        warnings.append("open-position count unavailable; downstream paper engine must re-check max-3 constraint")

    decision = APPROVED if not failures and not revision_items else (REJECTED if failures else NEEDS_REVISION)
    passed = decision == APPROVED
    feasibility_score = Decimal("0.900") if passed else (Decimal("0.250") if failures else Decimal("0.550"))
    risk_score = Decimal("0.250") if passed else (Decimal("0.900") if failures else Decimal("0.600"))

    constraint_check = {
        "passed": passed,
        "failures": failures,
        "revision_items": revision_items,
        "warnings": warnings,
        "required_fields_checked": REQUIRED_SQLITE_FIELDS,
        "active_positions": active_positions,
        "risk_reward_multiple": rr,
        "robinhood_assumption": rh,
        "jonah_refs": jonah_refs,
    }
    rationale_bits = []
    if failures:
        rationale_bits.append("Rejected: " + "; ".join(failures))
    if revision_items:
        rationale_bits.append("Needs revision: " + "; ".join(revision_items))
    if passed:
        rationale_bits.append("Approved by deterministic Sentinel checks: long-only, RH-assumed, stop/target/RR/sizing present, no foreign/manipulation veto detected.")
    if warnings:
        rationale_bits.append("Warnings: " + "; ".join(warnings))

    return {
        "recommendation_id": str(rec["id"]),
        "reviewer_agent": "Sentinel",
        "decision": decision,
        "feasibility_score": feasibility_score,
        "risk_score": risk_score,
        "constraint_check": constraint_check,
        "review_notes": " ".join(rationale_bits),
    }


def _write_postgres_reviews(rows: list[dict[str, Any]], pg_dsn: str = DEFAULT_PG_DSN) -> None:
    if not rows:
        return
    if psycopg is None or Jsonb is None:
        raise RuntimeError("psycopg is unavailable; cannot write Postgres recommendation_reviews")
    with psycopg.connect(pg_dsn) as conn:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO recommendation_reviews(
                        recommendation_id, reviewer_agent, decision, feasibility_score,
                        risk_score, constraint_check, review_notes
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        row["recommendation_id"],
                        row["reviewer_agent"],
                        row["decision"],
                        row["feasibility_score"],
                        row["risk_score"],
                        Jsonb(row["constraint_check"]),
                        row["review_notes"],
                    ),
                )


def _update_sqlite_statuses(db_path: str | Path, reviews: Iterable[Mapping[str, Any]]) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        for review in reviews:
            rec_id = int(review["recommendation_id"])
            current = con.execute("SELECT notes FROM recommendations WHERE id=?", (rec_id,)).fetchone()
            notes = _load_notes(current["notes"] if current is not None else None)
            notes["sentinel_review"] = {
                "reviewed_at": now,
                "decision": review["decision"],
                "constraint_check": review["constraint_check"],
                "review_notes": review["review_notes"],
            }
            con.execute(
                "UPDATE recommendations SET status=?, notes=? WHERE id=?",
                (review["decision"], json.dumps(notes, sort_keys=True), rec_id),
            )
        con.commit()
    finally:
        con.close()



def _pg_fetch_dicts(cur, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cur.execute(sql, params)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def pending_recommendations_postgres(pg_dsn: str = DEFAULT_PG_DSN, limit: int | None = None) -> list[dict[str, Any]]:
    """Return pending_review recommendations from Postgres primary in FIFO order."""
    if psycopg is None:
        raise RuntimeError("psycopg is unavailable; cannot read Postgres recommendations")
    sql = """
        SELECT id, ticker, action, recommendation_type, thesis, setup_type,
               entry_zone, entry_trigger, stop, target, risk_reward, confidence,
               position_size_suggestion, holding_period, status, notes, created_at
        FROM recommendations
        WHERE lower(status) = 'pending_review'
        ORDER BY created_at ASC, id ASC
    """
    params: tuple[Any, ...] = ()
    if limit is not None:
        sql += " LIMIT %s"
        params = (int(limit),)
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        return _pg_fetch_dicts(cur, sql, params)


def _active_position_count_postgres(pg_dsn: str = DEFAULT_PG_DSN) -> int | None:
    if psycopg is None:
        raise RuntimeError("psycopg is unavailable; cannot read Postgres paper_trades")
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) FROM paper_trades
            WHERE lower(COALESCE(status,'')) IN ('open','pending','triggered','active')
        """)
        return int(cur.fetchone()[0])


def _update_postgres_statuses(pg_dsn: str, reviews: Iterable[Mapping[str, Any]]) -> None:
    if psycopg is None or Jsonb is None:
        raise RuntimeError("psycopg is unavailable; cannot update Postgres recommendations")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with psycopg.connect(pg_dsn) as conn:
        with conn.cursor() as cur:
            for review in reviews:
                rec_id = int(review["recommendation_id"])
                cur.execute("SELECT notes FROM recommendations WHERE id=%s", (rec_id,))
                row = cur.fetchone()
                notes = row[0] if row and isinstance(row[0], dict) else _load_notes(row[0] if row else None)
                notes["sentinel_review"] = {"reviewed_at": now, "decision": review["decision"], "constraint_check": review["constraint_check"], "review_notes": review["review_notes"], "source": "postgres-primary"}
                cur.execute("UPDATE recommendations SET status=%s, notes=%s WHERE id=%s", (review["decision"], Jsonb(notes), rec_id))


def review_pending_recommendations_postgres(*, pg_dsn: str = DEFAULT_PG_DSN, dry_run: bool = False, limit: int | None = None, pg_writer: PGReviewWriter | None = None) -> dict[str, Any]:
    """Review Postgres-primary pending recommendations and update Postgres state."""
    rows = pending_recommendations_postgres(pg_dsn, limit=limit)
    active_positions = _active_position_count_postgres(pg_dsn)
    reviews = [evaluate_recommendation(row, active_positions=active_positions) for row in rows]
    if not dry_run and reviews:
        writer = pg_writer or (lambda payload: _write_postgres_reviews(payload, pg_dsn=pg_dsn))
        writer(reviews)
        _update_postgres_statuses(pg_dsn, reviews)
    return {
        "source": "postgres",
        "reviewed": len(reviews),
        "dry_run": dry_run,
        "decisions": {row["recommendation_id"]: row["decision"] for row in reviews},
        "reviews": [{**row, "feasibility_score": float(row["feasibility_score"]), "risk_score": float(row["risk_score"])} for row in reviews],
    }

def review_pending_recommendations(
    db_path: str | Path = DEFAULT_DB,
    *,
    pg_dsn: str = DEFAULT_PG_DSN,
    dry_run: bool = False,
    limit: int | None = None,
    pg_writer: PGReviewWriter | None = None,
) -> dict[str, Any]:
    """Review all pending recommendations, persist reviews, and update statuses."""
    rows = pending_recommendations(db_path, limit=limit)
    con = sqlite3.connect(db_path)
    try:
        active_positions = _active_position_count(con)
    finally:
        con.close()

    reviews = [evaluate_recommendation(row, active_positions=active_positions) for row in rows]
    if not dry_run and reviews:
        writer = pg_writer or (lambda payload: _write_postgres_reviews(payload, pg_dsn=pg_dsn))
        writer(reviews)
        _update_sqlite_statuses(db_path, reviews)

    return {
        "reviewed": len(reviews),
        "dry_run": dry_run,
        "decisions": {row["recommendation_id"]: row["decision"] for row in reviews},
        "reviews": [
            {
                **row,
                "feasibility_score": float(row["feasibility_score"]),
                "risk_score": float(row["risk_score"]),
            }
            for row in reviews
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Persist Sentinel reviews for pending Wolfy recommendations.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    parser.add_argument("--pg-dsn", default=DEFAULT_PG_DSN, help="Postgres DSN for recommendation_reviews")
    parser.add_argument("--limit", type=int, help="Maximum pending recommendations to review")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate but do not write sinks")
    parser.add_argument("--source", choices=["sqlite", "postgres"], default="sqlite", help="Recommendation source/status sink")
    args = parser.parse_args(argv)
    if args.source == "postgres":
        result = review_pending_recommendations_postgres(pg_dsn=args.pg_dsn, dry_run=args.dry_run, limit=args.limit)
    else:
        result = review_pending_recommendations(args.db, pg_dsn=args.pg_dsn, dry_run=args.dry_run, limit=args.limit)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
