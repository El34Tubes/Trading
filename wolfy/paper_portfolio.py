#!/usr/bin/env python3
"""Wolfy paper portfolio engine and outcome grader.

This module turns Sentinel-approved recommendations into delayed/free-data paper
trades only. It does not route live orders or claim execution. The first data
source is an injected quote map for tests/smoke runs; when omitted, it falls
back to latest SQLite scanner_results closes as delayed/free market data.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

DEFAULT_DB = Path("/root/.hermes/wolfy/wolfy.db")
ACCOUNT_SIZE = 5000.0
MAX_OPEN_POSITIONS = 3
DEFAULT_RISK_FRACTION = 0.0075
ACTIVE_STATUSES = {"open", "pending", "triggered", "active"}

PAPER_TRADES_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  recommendation_id INTEGER REFERENCES recommendations(id),
  ticker TEXT NOT NULL,
  entry_date TEXT,
  entry_price REAL,
  quantity REAL,
  qty REAL,
  opened_at TEXT,
  closed_at TEXT,
  instrument TEXT DEFAULT 'equity_or_etf',
  stop_price REAL,
  target_price REAL,
  exit_date TEXT,
  exit_price REAL,
  exit_reason TEXT,
  pnl REAL,
  r_multiple REAL,
  days_held INTEGER,
  status TEXT NOT NULL DEFAULT 'planned',
  max_favorable_excursion REAL,
  max_drawdown REAL,
  data_source TEXT,
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON paper_trades(status);
CREATE INDEX IF NOT EXISTS idx_paper_trades_recommendation ON paper_trades(recommendation_id);
CREATE INDEX IF NOT EXISTS idx_paper_trades_ticker ON paper_trades(ticker);
"""

OUTCOMES_SCHEMA = """
CREATE TABLE IF NOT EXISTS recommendation_outcomes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  recommendation_id INTEGER NOT NULL REFERENCES recommendations(id) ON DELETE CASCADE,
  paper_trade_id INTEGER REFERENCES paper_trades(id) ON DELETE SET NULL,
  entry_triggered INTEGER DEFAULT 0,
  hit_stop INTEGER DEFAULT 0,
  hit_target INTEGER DEFAULT 0,
  max_gain_pct REAL,
  max_drawdown_pct REAL,
  max_favorable_excursion REAL,
  max_drawdown REAL,
  r_multiple REAL,
  pnl REAL,
  days_held INTEGER,
  exit_reason TEXT,
  thesis_correct INTEGER,
  notes TEXT,
  graded_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_recommendation_outcomes_rec ON recommendation_outcomes(recommendation_id, graded_at DESC);
"""

PAPER_EXTRA_COLUMNS = {
    "max_favorable_excursion": "REAL",
    "max_drawdown": "REAL",
    "data_source": "TEXT",
    "notes": "TEXT",
    "qty": "REAL",
    "opened_at": "TEXT",
    "closed_at": "TEXT",
}
OUTCOME_EXTRA_COLUMNS = {
    "paper_trade_id": "INTEGER REFERENCES paper_trades(id) ON DELETE SET NULL",
    "max_favorable_excursion": "REAL",
    "max_drawdown": "REAL",
    "pnl": "REAL",
    "days_held": "INTEGER",
    "exit_reason": "TEXT",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_paper_tables(db_path: str | Path = DEFAULT_DB) -> None:
    """Create/upgrade paper_trades and recommendation_outcomes for grading."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        con.executescript(PAPER_TRADES_SCHEMA)
        con.executescript(OUTCOMES_SCHEMA)
        _ensure_columns(con, "paper_trades", PAPER_EXTRA_COLUMNS)
        _ensure_columns(con, "recommendation_outcomes", OUTCOME_EXTRA_COLUMNS)
        con.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS trg_paper_trades_alias_after_insert
            AFTER INSERT ON paper_trades
            FOR EACH ROW
            WHEN NEW.qty IS NULL OR NEW.opened_at IS NULL OR NEW.closed_at IS NULL
            BEGIN
              UPDATE paper_trades
              SET qty=COALESCE(NEW.qty, NEW.quantity),
                  opened_at=COALESCE(NEW.opened_at, NEW.entry_date),
                  closed_at=COALESCE(NEW.closed_at, NEW.exit_date)
              WHERE id=NEW.id;
            END;
            CREATE TRIGGER IF NOT EXISTS trg_paper_trades_alias_after_update
            AFTER UPDATE OF quantity, entry_date, exit_date, qty, opened_at, closed_at ON paper_trades
            FOR EACH ROW
            WHEN NEW.qty IS NULL OR NEW.opened_at IS NULL OR NEW.closed_at IS NULL
            BEGIN
              UPDATE paper_trades
              SET qty=COALESCE(NEW.qty, NEW.quantity),
                  opened_at=COALESCE(NEW.opened_at, NEW.entry_date),
                  closed_at=COALESCE(NEW.closed_at, NEW.exit_date)
              WHERE id=NEW.id;
            END;
            """
        )
        con.commit()
    finally:
        con.close()


def _ensure_columns(con: sqlite3.Connection, table: str, columns: Mapping[str, str]) -> None:
    existing = {row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, ddl in columns.items():
        if name not in existing:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_price(text: Any) -> float | None:
    s = _clean(text).replace(",", "")
    if not s:
        return None
    matches = re.findall(r"(?:\$)?(\d+(?:\.\d+)?)", s)
    return float(matches[0]) if matches else None


def _field(rec: Mapping[str, Any] | sqlite3.Row, key: str) -> Any:
    if isinstance(rec, sqlite3.Row):
        return rec[key] if key in rec.keys() else None
    return rec.get(key)


def _parse_entry_trigger_price(rec: Mapping[str, Any] | sqlite3.Row) -> float | None:
    return _parse_price(_field(rec, "entry_trigger")) or _parse_price(_field(rec, "entry_zone"))


def _parse_stop_price(rec: Mapping[str, Any] | sqlite3.Row) -> float | None:
    return _parse_price(_field(rec, "stop"))


def _parse_target_price(rec: Mapping[str, Any] | sqlite3.Row) -> float | None:
    return _parse_price(_field(rec, "target"))


def _as_quote_map(quotes: Mapping[str, Mapping[str, Any]] | None) -> dict[str, dict[str, Any]]:
    if not quotes:
        return {}
    return {str(k).upper(): dict(v) for k, v in quotes.items()}


def load_latest_scanner_quotes(db_path: str | Path = DEFAULT_DB) -> dict[str, dict[str, Any]]:
    """Return latest scanner close per ticker as delayed/free quote data."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        table = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='scanner_results'").fetchone()
        if table is None:
            return {}
        rows = con.execute(
            """
            SELECT sr.ticker, sr.data_date, sr.close, sr.high20, sr.low20
            FROM scanner_results sr
            JOIN (
                SELECT ticker, MAX(COALESCE(data_date, created_at)) AS max_date
                FROM scanner_results
                GROUP BY ticker
            ) latest ON latest.ticker=sr.ticker AND latest.max_date=COALESCE(sr.data_date, sr.created_at)
            WHERE sr.close IS NOT NULL
            """
        ).fetchall()
        return {
            row["ticker"].upper(): {
                "date": row["data_date"] or date.today().isoformat(),
                "close": row["close"],
                "high": row["high20"] or row["close"],
                "low": row["low20"] or row["close"],
                "source": "sqlite_scanner_results_delayed_or_free",
            }
            for row in rows
        }
    finally:
        con.close()


def _quote_for(ticker: str, quotes: Mapping[str, Mapping[str, Any]]) -> dict[str, Any] | None:
    quote = quotes.get(ticker.upper())
    if not quote:
        return None
    out = dict(quote)
    out.setdefault("date", date.today().isoformat())
    out.setdefault("high", out.get("close"))
    out.setdefault("low", out.get("close"))
    out.setdefault("source", "delayed_or_free_quote")
    return out


def _open_position_count(con: sqlite3.Connection) -> int:
    statuses = tuple(ACTIVE_STATUSES)
    placeholders = ",".join("?" for _ in statuses)
    return int(
        con.execute(
            f"SELECT COUNT(*) FROM paper_trades WHERE lower(COALESCE(status,'')) IN ({placeholders})",
            statuses,
        ).fetchone()[0]
    )


def _approved_candidates(con: sqlite3.Connection) -> list[sqlite3.Row]:
    con.row_factory = sqlite3.Row
    return con.execute(
        """
        SELECT r.* FROM recommendations r
        WHERE lower(r.status) = 'approved'
          AND lower(COALESCE(r.action,'')) IN ('buy','long','call','calls','buy_call','buy_calls','call_option','debit_call_spread','hold')
          AND NOT EXISTS (SELECT 1 FROM paper_trades pt WHERE pt.recommendation_id = r.id)
        ORDER BY r.timestamp ASC, r.id ASC
        """
    ).fetchall()


def _sized_quantity(entry_price: float, stop_price: float) -> float:
    risk_per_share = max(entry_price - stop_price, 0.01)
    risk_budget = ACCOUNT_SIZE * DEFAULT_RISK_FRACTION
    qty = int(risk_budget // risk_per_share)
    return float(max(1, qty))


def _record_outcome(
    con: sqlite3.Connection,
    *,
    recommendation_id: int,
    paper_trade_id: int | None,
    entry_triggered: int,
    hit_stop: int = 0,
    hit_target: int = 0,
    max_gain_pct: float | None = None,
    max_drawdown_pct: float | None = None,
    max_favorable_excursion: float | None = None,
    max_drawdown: float | None = None,
    r_multiple: float | None = None,
    pnl: float | None = None,
    days_held: int | None = None,
    exit_reason: str | None = None,
    notes: Mapping[str, Any] | None = None,
) -> None:
    con.execute(
        """
        INSERT INTO recommendation_outcomes(
            recommendation_id,paper_trade_id,entry_triggered,hit_stop,hit_target,
            max_gain_pct,max_drawdown_pct,max_favorable_excursion,max_drawdown,
            r_multiple,pnl,days_held,exit_reason,notes,graded_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            recommendation_id,
            paper_trade_id,
            entry_triggered,
            hit_stop,
            hit_target,
            max_gain_pct,
            max_drawdown_pct,
            max_favorable_excursion,
            max_drawdown,
            r_multiple,
            pnl,
            days_held,
            exit_reason,
            json.dumps(dict(notes or {}), sort_keys=True),
            _now(),
        ),
    )


def open_approved_recommendations(
    db_path: str | Path = DEFAULT_DB,
    *,
    quotes: Mapping[str, Mapping[str, Any]] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Open paper trades for approved recommendations whose entry trigger fired."""
    ensure_paper_tables(db_path)
    quote_map = _as_quote_map(quotes) or load_latest_scanner_quotes(db_path)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    opened = would_open = skipped_no_quote = skipped_no_trigger = blocked_max_positions = 0
    planned: list[dict[str, Any]] = []
    try:
        active = _open_position_count(con)
        for rec in _approved_candidates(con):
            quote = _quote_for(rec["ticker"], quote_map)
            if quote is None or quote.get("close") is None:
                skipped_no_quote += 1
                continue
            entry_trigger = _parse_entry_trigger_price(rec)
            stop_price = _parse_stop_price(rec)
            target_price = _parse_target_price(rec)
            close = float(quote["close"])
            if entry_trigger is None or stop_price is None or target_price is None:
                skipped_no_trigger += 1
                continue
            if close < entry_trigger:
                skipped_no_trigger += 1
                continue
            if active >= MAX_OPEN_POSITIONS:
                blocked_max_positions += 1
                continue
            qty = _sized_quantity(close, stop_price)
            would_open += 1
            trade = {
                "recommendation_id": rec["id"],
                "ticker": rec["ticker"],
                "entry_date": str(quote["date"]),
                "entry_price": close,
                "quantity": qty,
                "stop_price": stop_price,
                "target_price": target_price,
                "data_source": quote.get("source", "delayed_or_free_quote"),
            }
            planned.append(trade)
            if not dry_run:
                cur = con.execute(
                    """
                    INSERT INTO paper_trades(
                        recommendation_id,ticker,entry_date,entry_price,quantity,qty,opened_at,
                        instrument,stop_price,target_price,status,data_source,notes
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        trade["recommendation_id"], trade["ticker"], trade["entry_date"],
                        trade["entry_price"], trade["quantity"], trade["quantity"], trade["entry_date"],
                        rec["recommendation_type"] or "equity_or_etf", trade["stop_price"],
                        trade["target_price"], "open", trade["data_source"],
                        json.dumps({"paper_only": True, "opened_by": "paper_portfolio.py", "source": trade["data_source"]}, sort_keys=True),
                    ),
                )
                _record_outcome(
                    con,
                    recommendation_id=int(rec["id"]),
                    paper_trade_id=cur.lastrowid,
                    entry_triggered=1,
                    notes={"source": trade["data_source"], "paper_only": True},
                )
                opened += 1
                active += 1
        if not dry_run:
            con.commit()
    finally:
        con.close()
    return {
        "dry_run": dry_run,
        "opened": opened,
        "would_open": would_open,
        "planned": planned,
        "skipped_no_quote": skipped_no_quote,
        "skipped_no_trigger": skipped_no_trigger,
        "blocked_max_positions": blocked_max_positions,
        "max_positions": MAX_OPEN_POSITIONS,
        "account_size": ACCOUNT_SIZE,
    }


def _days_between(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        return (datetime.fromisoformat(end[:10]).date() - datetime.fromisoformat(start[:10]).date()).days
    except ValueError:
        return None


def _open_trades(con: sqlite3.Connection) -> list[sqlite3.Row]:
    con.row_factory = sqlite3.Row
    statuses = tuple(ACTIVE_STATUSES)
    placeholders = ",".join("?" for _ in statuses)
    return con.execute(
        f"SELECT * FROM paper_trades WHERE lower(COALESCE(status,'')) IN ({placeholders}) ORDER BY entry_date ASC, id ASC",
        statuses,
    ).fetchall()


def grade_open_trades(
    db_path: str | Path = DEFAULT_DB,
    *,
    quotes: Mapping[str, Mapping[str, Any]] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Grade open paper trades against stop/target and record PnL/R/MFE/MAE."""
    ensure_paper_tables(db_path)
    quote_map = _as_quote_map(quotes) or load_latest_scanner_quotes(db_path)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    closed = updated = skipped_no_quote = 0
    details: list[dict[str, Any]] = []
    try:
        for trade in _open_trades(con):
            quote = _quote_for(trade["ticker"], quote_map)
            if quote is None or quote.get("close") is None:
                skipped_no_quote += 1
                continue
            entry = float(trade["entry_price"])
            qty = float(trade["quantity"] or trade["qty"] or 1.0)
            stop = float(trade["stop_price"])
            target = float(trade["target_price"])
            high = float(quote.get("high") if quote.get("high") is not None else quote["close"])
            low = float(quote.get("low") if quote.get("low") is not None else quote["close"])
            close = float(quote["close"])
            mfe = round(high - entry, 4)
            mae = round(low - entry, 4)
            max_gain_pct = round((high - entry) / entry * 100, 4)
            max_drawdown_pct = round((low - entry) / entry * 100, 4)
            exit_reason = None
            exit_price = None
            if low <= stop:
                exit_reason = "stop"
                exit_price = stop
            elif high >= target or close >= target:
                exit_reason = "target"
                exit_price = target
            current_r = round((close - entry) / max(entry - stop, 0.01), 4)
            days_held = _days_between(trade["entry_date"] or trade["opened_at"], str(quote["date"]))
            hit_stop = 1 if exit_reason == "stop" else 0
            hit_target = 1 if exit_reason == "target" else 0
            final_price = exit_price if exit_price is not None else close
            pnl = round((final_price - entry) * qty, 4)
            r_multiple = round((final_price - entry) / max(entry - stop, 0.01), 4)
            detail = {
                "paper_trade_id": trade["id"],
                "ticker": trade["ticker"],
                "status": "closed" if exit_reason else "open",
                "exit_reason": exit_reason,
                "pnl": pnl,
                "r_multiple": r_multiple if exit_reason else current_r,
                "days_held": days_held,
                "max_favorable_excursion": mfe,
                "max_drawdown": mae,
            }
            details.append(detail)
            if not dry_run:
                if exit_reason:
                    con.execute(
                        """
                        UPDATE paper_trades
                        SET status='closed', exit_date=?, closed_at=?, exit_price=?, exit_reason=?, pnl=?,
                            r_multiple=?, days_held=?, max_favorable_excursion=?, max_drawdown=?, data_source=?
                        WHERE id=?
                        """,
                        (str(quote["date"]), str(quote["date"]), exit_price, exit_reason, pnl, r_multiple,
                         days_held, mfe, mae, quote.get("source", "delayed_or_free_quote"), trade["id"]),
                    )
                    closed += 1
                else:
                    con.execute(
                        """
                        UPDATE paper_trades
                        SET r_multiple=?, days_held=?, max_favorable_excursion=?, max_drawdown=?, data_source=?
                        WHERE id=?
                        """,
                        (current_r, days_held, mfe, mae, quote.get("source", "delayed_or_free_quote"), trade["id"]),
                    )
                    updated += 1
                _record_outcome(
                    con,
                    recommendation_id=int(trade["recommendation_id"]),
                    paper_trade_id=int(trade["id"]),
                    entry_triggered=1,
                    hit_stop=hit_stop,
                    hit_target=hit_target,
                    max_gain_pct=max_gain_pct,
                    max_drawdown_pct=max_drawdown_pct,
                    max_favorable_excursion=mfe,
                    max_drawdown=mae,
                    r_multiple=r_multiple if exit_reason else current_r,
                    pnl=pnl if exit_reason else None,
                    days_held=days_held,
                    exit_reason=exit_reason,
                    notes={"source": quote.get("source", "delayed_or_free_quote"), "paper_only": True},
                )
        if not dry_run:
            con.commit()
    finally:
        con.close()
    return {"dry_run": dry_run, "closed": closed, "updated": updated, "skipped_no_quote": skipped_no_quote, "details": details}


def run_paper_engine(
    db_path: str | Path = DEFAULT_DB,
    *,
    quotes: Mapping[str, Mapping[str, Any]] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    quote_map = _as_quote_map(quotes) or load_latest_scanner_quotes(db_path)
    graded = grade_open_trades(db_path, quotes=quote_map, dry_run=dry_run)
    opened = open_approved_recommendations(db_path, quotes=quote_map, dry_run=dry_run)
    return {"dry_run": dry_run, "data_policy": "delayed/free data only; no live execution", "grade": graded, "open": opened}


def _load_quotes_file(path: str | None) -> dict[str, dict[str, Any]] | None:
    if not path:
        return None
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise SystemExit("quotes file must be a JSON object keyed by ticker")
    return {str(k).upper(): dict(v) for k, v in data.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Wolfy paper portfolio engine using delayed/free quote data only.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    parser.add_argument("--quotes-file", help="Optional JSON quote map keyed by ticker for dry-run/smoke tests")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate without writing paper_trades/recommendation_outcomes")
    args = parser.parse_args(argv)
    result = run_paper_engine(args.db, quotes=_load_quotes_file(args.quotes_file), dry_run=args.dry_run)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
