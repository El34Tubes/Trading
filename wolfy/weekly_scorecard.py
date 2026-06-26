#!/usr/bin/env python3
"""Wolfy weekly performance scorecard and learning-loop report.

The scorecard is deliberately deterministic: it reads persisted Wolfy
recommendations, Sentinel review notes, paper trades, and outcomes; computes the
weekly accountability metrics; renders a concise Discord-ready summary; and can
store that report in the reports table. It does not create recommendations,
approve trades, or touch broker/live execution paths.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

DEFAULT_DB = Path("/root/.hermes/wolfy/wolfy.db")
REPORT_TYPE = "wolfy_weekly_scorecard"
SOURCE_JOB_ID = "weekly_scorecard.py"

REPORTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT NOT NULL DEFAULT (datetime('now')),
  report_type TEXT NOT NULL,
  content TEXT NOT NULL,
  delivered_to TEXT,
  source_job_id TEXT
);
"""


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _window(as_of: str | datetime | None, lookback_days: int) -> tuple[datetime, datetime]:
    end = _parse_dt(as_of) if as_of is not None else _now_utc()
    if end is None:
        raise ValueError(f"invalid as_of timestamp: {as_of!r}")
    return end - timedelta(days=int(lookback_days)), end


def _load_json_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    text = str(value).strip()
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
    if isinstance(value, set):
        return sorted(value)
    return [value]


def _clean_reason(reason: Any) -> str:
    text = str(reason or "").strip()
    return text or "unspecified review rejection/revision reason"


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _row_date(row: Mapping[str, Any], keys: Iterable[str]) -> datetime | None:
    for key in keys:
        dt = _parse_dt(row.get(key))
        if dt is not None:
            return dt
    return None


def _in_window(row: Mapping[str, Any], keys: Iterable[str], start: datetime, end: datetime) -> bool:
    dt = _row_date(row, keys)
    return dt is not None and start <= dt <= end


def _fetch_rows(con: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    if not _table_exists(con, table):
        return []
    con.row_factory = sqlite3.Row
    return [dict(row) for row in con.execute(f"SELECT * FROM {table}").fetchall()]


def _sentinel_reason_counter(recommendations: list[dict[str, Any]]) -> Counter[str]:
    reasons: Counter[str] = Counter()
    for rec in recommendations:
        notes = _load_json_dict(rec.get("notes"))
        review_raw = notes.get("sentinel_review")
        review: dict[str, Any] = review_raw if isinstance(review_raw, dict) else {}
        decision = str(review.get("decision") or rec.get("status") or "").lower()
        if decision not in {"rejected", "needs_revision"} and str(rec.get("status") or "").lower() not in {"rejected", "needs_revision"}:
            continue
        check_raw = review.get("constraint_check")
        check: dict[str, Any] = check_raw if isinstance(check_raw, dict) else {}
        collected = []
        collected.extend(_as_list(check.get("failures")))
        collected.extend(_as_list(check.get("revision_items")))
        if not collected and review.get("review_notes"):
            collected.append(review.get("review_notes"))
        if not collected:
            collected.append(f"Sentinel {decision or rec.get('status')} without structured reason")
        for reason in collected:
            reasons[_clean_reason(reason)] += 1
    return reasons


def _trade_is_winner(trade: Mapping[str, Any]) -> bool:
    reason = str(trade.get("exit_reason") or "").lower()
    if reason == "target":
        return True
    try:
        return float(trade.get("pnl") or 0) > 0 or float(trade.get("r_multiple") or 0) > 0
    except (TypeError, ValueError):
        return False


def _float_values(rows: Iterable[Mapping[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get(key)
        if value in (None, ""):
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return values


def _rule_changes_needed(reasons: Counter[str], closed_trades: list[dict[str, Any]], summary: Mapping[str, Any]) -> list[str]:
    changes: list[str] = []
    if reasons:
        top_reason, count = reasons.most_common(1)[0]
        changes.append(f"Tighten pre-Sentinel rejection filters around '{top_reason}' ({count} occurrence{'s' if count != 1 else ''}).")
    hit_rate = summary.get("hit_rate")
    if hit_rate is not None and float(hit_rate) < 0.5 and closed_trades:
        changes.append("Raise setup quality bar: weekly hit rate below 50%, require stronger EOD confirmation before paper entry.")
    avg_r = summary.get("avg_r")
    if avg_r is not None and float(avg_r) < 0 and closed_trades:
        changes.append("Cut losers faster or improve target selection: average R is negative for closed paper trades.")
    if not changes:
        changes.append("No forced rule change this week; keep current max-3, stop-required, EOD-only process and collect more samples.")
    return changes


def _jonah_priorities(reasons: Counter[str], closed_trades: list[dict[str, Any]]) -> list[str]:
    priorities: list[str] = []
    reason_text = " | ".join(reasons.keys()).lower()
    if "risk/reward" in reason_text or "2r" in reason_text:
        priorities.append("Jonah: research risk/reward setups that reliably produce >=2R swing targets before Sentinel review.")
    if "foreign" in reason_text or "manipulation" in reason_text or "government" in reason_text:
        priorities.append("Jonah: expand U.S.-listed/liquid-only negative filters for foreign, opaque, pump-like, and government-interference risk.")
    if "jonah" in reason_text or "knowledge" in reason_text or "strategy" in reason_text:
        priorities.append("Jonah: improve source/reference coverage so every actionable idea has linked strategy evidence.")
    stopped = [trade for trade in closed_trades if str(trade.get("exit_reason") or "").lower() == "stop"]
    if stopped:
        tickers = ", ".join(sorted({str(t.get("ticker", "")).upper() for t in stopped if t.get("ticker")}))
        priorities.append(f"Jonah: review stop-outs ({tickers}) for recurring failed setup traits and regime filters.")
    if not priorities:
        priorities.append("Jonah: keep building evidence on closed winners/losers; no single rejection cluster dominated this week.")
    return priorities[:4]


def build_weekly_scorecard(
    db_path: str | Path = DEFAULT_DB,
    *,
    as_of: str | datetime | None = None,
    lookback_days: int = 7,
) -> dict[str, Any]:
    """Compute weekly Wolfy performance and learning-loop metrics."""
    start, end = _window(as_of, lookback_days)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        recommendations = [
            row for row in _fetch_rows(con, "recommendations")
            if _in_window(row, ("timestamp",), start, end)
        ]
        trades = [
            row for row in _fetch_rows(con, "paper_trades")
            if _in_window(row, ("exit_date", "closed_at", "entry_date", "opened_at"), start, end)
        ]
        outcomes = [
            row for row in _fetch_rows(con, "recommendation_outcomes")
            if _in_window(row, ("graded_at",), start, end)
        ]
    finally:
        con.close()

    closed_trades = [row for row in trades if str(row.get("status") or "").lower() == "closed" or row.get("exit_date") or row.get("closed_at")]
    winners = [row for row in closed_trades if _trade_is_winner(row)]
    r_values = _float_values(closed_trades, "r_multiple")
    drawdowns = _float_values(closed_trades, "max_drawdown") or _float_values(outcomes, "max_drawdown")
    reasons = _sentinel_reason_counter(recommendations)
    approved = sum(1 for row in recommendations if str(row.get("status") or "").lower() == "approved")
    rejected = sum(1 for row in recommendations if str(row.get("status") or "").lower() == "rejected")
    needs_revision = sum(1 for row in recommendations if str(row.get("status") or "").lower() == "needs_revision")

    summary = {
        "window_start": start.date().isoformat(),
        "window_end": end.date().isoformat(),
        "recommendations_reviewed": len(recommendations),
        "approved": approved,
        "rejected": rejected,
        "needs_revision": needs_revision,
        "paper_trades": len(trades),
        "closed_trades": len(closed_trades),
        "wins": len(winners),
        "losses": max(len(closed_trades) - len(winners), 0),
        "hit_rate": round(len(winners) / len(closed_trades), 4) if closed_trades else None,
        "avg_r": round(sum(r_values) / len(r_values), 4) if r_values else None,
        "max_drawdown_r": round(min(drawdowns), 4) if drawdowns else None,
    }
    return {
        "as_of": end.isoformat(timespec="seconds"),
        "lookback_days": int(lookback_days),
        "summary": summary,
        "rejected_trade_reasons": dict(reasons.most_common()),
        "rule_changes_needed": _rule_changes_needed(reasons, closed_trades, summary),
        "jonah_research_priorities": _jonah_priorities(reasons, closed_trades),
        "closed_trades": [
            {
                "ticker": row.get("ticker"),
                "exit_reason": row.get("exit_reason"),
                "pnl": row.get("pnl"),
                "r_multiple": row.get("r_multiple"),
                "max_drawdown": row.get("max_drawdown"),
                "days_held": row.get("days_held"),
            }
            for row in closed_trades
        ],
    }


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.1f}%"


def _fmt_r(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.2f}R"


def _bullet_lines(items: Mapping[str, Any] | Iterable[Any], *, empty: str) -> list[str]:
    if isinstance(items, Mapping):
        pairs = list(items.items())
        if not pairs:
            return [f"- {empty}"]
        return [f"- {key}: {value}" for key, value in pairs]
    values = list(items)
    if not values:
        return [f"- {empty}"]
    return [f"- {value}" for value in values]


def render_discord_report(scorecard: Mapping[str, Any]) -> str:
    """Render a concise Discord-ready Wolfy weekly report."""
    summary = scorecard["summary"]
    lines = [
        f"Wolfy Weekly Scorecard ({summary['window_start']} -> {summary['window_end']})",
        f"Reviews: {summary['recommendations_reviewed']} | Approved: {summary['approved']} | Rejected: {summary['rejected']} | Needs revision: {summary['needs_revision']}",
        f"Paper trades closed: {summary['closed_trades']} | Hit rate: {_fmt_pct(summary['hit_rate'])} | Avg R: {_fmt_r(summary['avg_r'])} | Max drawdown: {_fmt_r(summary['max_drawdown_r'])}",
        "Rejected / revised trade reasons:",
        *_bullet_lines(scorecard.get("rejected_trade_reasons", {}), empty="none logged"),
        "Rule changes needed:",
        *_bullet_lines(scorecard.get("rule_changes_needed", []), empty="none"),
        "Jonah research priorities:",
        *_bullet_lines(scorecard.get("jonah_research_priorities", []), empty="none"),
        "Discipline: EOD-only, paper account only, long-only/RH-tradable, max 3 positions, stops required.",
    ]
    return "\n".join(lines)


def ensure_reports_table(db_path: str | Path = DEFAULT_DB) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.executescript(REPORTS_SCHEMA)
        con.commit()
    finally:
        con.close()


def store_weekly_scorecard_report(
    db_path: str | Path,
    report: str,
    *,
    delivered_to: str = "discord_ready",
    source_job_id: str = SOURCE_JOB_ID,
) -> int:
    """Persist the rendered scorecard in reports and return its report id."""
    ensure_reports_table(db_path)
    con = sqlite3.connect(db_path)
    try:
        cur = con.execute(
            "INSERT INTO reports (timestamp, report_type, content, delivered_to, source_job_id) VALUES (?, ?, ?, ?, ?)",
            (_now_utc().isoformat(timespec="seconds"), REPORT_TYPE, report, delivered_to, source_job_id),
        )
        con.commit()
        if cur.lastrowid is None:
            raise RuntimeError("reports insert did not return a row id")
        return int(cur.lastrowid)
    finally:
        con.close()


def run_weekly_scorecard(
    db_path: str | Path = DEFAULT_DB,
    *,
    as_of: str | datetime | None = None,
    lookback_days: int = 7,
    store: bool = False,
) -> dict[str, Any]:
    scorecard = build_weekly_scorecard(db_path, as_of=as_of, lookback_days=lookback_days)
    report = render_discord_report(scorecard)
    report_id = store_weekly_scorecard_report(db_path, report) if store else None
    return {"scorecard": scorecard, "report": report, "report_id": report_id}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Wolfy's weekly paper-trading performance scorecard.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite compatibility DB path")
    parser.add_argument("--as-of", help="UTC timestamp/date ending the scorecard window")
    parser.add_argument("--lookback-days", type=int, default=7, help="Window length; default 7 days")
    parser.add_argument("--store", action="store_true", help="Store rendered scorecard in reports")
    parser.add_argument("--json", action="store_true", help="Print JSON payload instead of rendered report")
    args = parser.parse_args(argv)
    result = run_weekly_scorecard(args.db, as_of=args.as_of, lookback_days=args.lookback_days, store=args.store)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(result["report"])
        if result["report_id"] is not None:
            print(f"\nStored report_id={result['report_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
