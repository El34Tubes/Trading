#!/usr/bin/env python3
"""Postgres-primary operational helpers for Wolfy migration P10.

These helpers are intentionally small and boring: create missing compatibility
relations non-destructively, write Postgres first, and let legacy SQLite callers
remain explicit compatibility sinks while cron/report code can warn on fallback.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import json
from typing import Any, Mapping

from psycopg.types.json import Jsonb

from wolfy_db import DEFAULT_POSTGRES_DSN, connect_postgres as _connect_postgres


def connect_postgres(dsn: str | None = None):
    if dsn:
        from wolfy_db import DatabaseConfig

        return _connect_postgres(DatabaseConfig(postgres_dsn=dsn))
    return _connect_postgres()


def ensure_operational_tables(conn) -> None:
    """Create Postgres-primary operational tables missing from the P8/P9 schema."""
    statements = [

        """
        CREATE TABLE IF NOT EXISTS universe_symbols (
          symbol TEXT PRIMARY KEY,
          name TEXT,
          source TEXT NOT NULL,
          sector TEXT,
          is_etf BOOLEAN NOT NULL DEFAULT false,
          last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
          active BOOLEAN NOT NULL DEFAULT true
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_pg_universe_symbols_active_source ON universe_symbols(active, source)",
        "CREATE INDEX IF NOT EXISTS idx_pg_universe_symbols_etf ON universe_symbols(is_etf, active)",
        """
        CREATE TABLE IF NOT EXISTS scanner_runs (
          id BIGSERIAL PRIMARY KEY,
          sqlite_id BIGINT UNIQUE,
          run_time TIMESTAMPTZ NOT NULL DEFAULT now(),
          data_source TEXT NOT NULL,
          universe TEXT,
          notes TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_pg_scanner_runs_time ON scanner_runs(run_time DESC)",
        """
        CREATE TABLE IF NOT EXISTS scanner_results (
          id BIGSERIAL PRIMARY KEY,
          sqlite_id BIGINT UNIQUE,
          run_id BIGINT NOT NULL REFERENCES scanner_runs(id) ON DELETE CASCADE,
          ticker TEXT NOT NULL,
          score DOUBLE PRECISION,
          data_date DATE,
          close DOUBLE PRECISION,
          r5 DOUBLE PRECISION,
          r20 DOUBLE PRECISION,
          r60 DOUBLE PRECISION,
          vs20 DOUBLE PRECISION,
          vs50 DOUBLE PRECISION,
          atr DOUBLE PRECISION,
          avg_volume DOUBLE PRECISION,
          high20 DOUBLE PRECISION,
          low20 DOUBLE PRECISION,
          extension_penalty DOUBLE PRECISION,
          liquidity_pass BOOLEAN,
          scanner_run_id BIGINT,
          status TEXT,
          company_name TEXT,
          scanner_type TEXT,
          rs_spy_20 DOUBLE PRECISION,
          rs_qqq_20 DOUBLE PRECISION,
          breakout_20d_pct DOUBLE PRECISION,
          volume_surge_1d_20 DOUBLE PRECISION,
          volume_surge_5d_20 DOUBLE PRECISION,
          volume_surge_1d_50 DOUBLE PRECISION,
          volume_surge_5d_50 DOUBLE PRECISION,
          atr_pct DOUBLE PRECISION,
          squeeze_ratio DOUBLE PRECISION,
          squeeze_flag INTEGER,
          liquidity_spread_proxy DOUBLE PRECISION,
          trend_regime TEXT,
          rank_reasons TEXT,
          gap_reversal_flag TEXT,
          notes JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(run_id, ticker)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_pg_scanner_results_run ON scanner_results(run_id, score DESC)",
        "CREATE INDEX IF NOT EXISTS idx_pg_scanner_results_ticker ON scanner_results(ticker, data_date DESC)",
        """
        CREATE TABLE IF NOT EXISTS recommendations (
          id BIGSERIAL PRIMARY KEY,
          sqlite_id BIGINT UNIQUE,
          report_id TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
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
          notes JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_pg_recommendations_status ON recommendations(status, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_pg_recommendations_ticker ON recommendations(ticker, created_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS paper_trades (
          id BIGSERIAL PRIMARY KEY,
          sqlite_id BIGINT UNIQUE,
          recommendation_id TEXT,
          ticker TEXT NOT NULL,
          entry_date DATE,
          entry_price DOUBLE PRECISION,
          quantity DOUBLE PRECISION,
          instrument TEXT DEFAULT 'equity_or_etf',
          stop_price DOUBLE PRECISION,
          target_price DOUBLE PRECISION,
          exit_date DATE,
          exit_price DOUBLE PRECISION,
          exit_reason TEXT,
          pnl DOUBLE PRECISION,
          r_multiple DOUBLE PRECISION,
          days_held INTEGER,
          status TEXT NOT NULL DEFAULT 'planned',
          data_source TEXT,
          notes JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_pg_paper_trades_status ON paper_trades(status, ticker)",
        """
        CREATE TABLE IF NOT EXISTS recommendation_outcomes (
          id BIGSERIAL PRIMARY KEY,
          sqlite_id BIGINT UNIQUE,
          recommendation_id TEXT NOT NULL,
          paper_trade_id TEXT,
          entry_triggered BOOLEAN DEFAULT false,
          hit_stop BOOLEAN DEFAULT false,
          hit_target BOOLEAN DEFAULT false,
          max_gain_pct DOUBLE PRECISION,
          max_drawdown_pct DOUBLE PRECISION,
          r_multiple DOUBLE PRECISION,
          pnl DOUBLE PRECISION,
          days_held INTEGER,
          exit_reason TEXT,
          notes JSONB NOT NULL DEFAULT '{}'::jsonb,
          graded_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_pg_recommendation_outcomes_rec ON recommendation_outcomes(recommendation_id, graded_at DESC)",
    ]
    with conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)
    conn.commit()


def _jsonb(value: Any) -> Jsonb:
    return Jsonb(value if value is not None else {})


def _date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def count_rows(conn, table: str) -> int:
    if table not in {"scanner_runs", "scanner_results", "recommendations", "paper_trades", "recommendation_outcomes"}:
        raise ValueError(f"count_rows table not allowlisted: {table}")
    ensure_operational_tables(conn)
    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {table}")
        return int(cur.fetchone()[0])


def persist_scanner_run(ranked: list[tuple[float, str, dict]], *, universe: str, notes: str, dsn: str | None = None) -> int:
    """Persist a scanner run and ranked rows to Postgres first."""
    with connect_postgres(dsn) as conn:
        ensure_operational_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO scanner_runs(data_source, universe, notes) VALUES(%s,%s,%s) RETURNING id",
                ("Yahoo chart endpoint", universe, notes),
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("Postgres did not return scanner_runs.id")
            run_id = int(row[0])
            for score, ticker, values in ranked:
                factor_payload = {
                    key: values.get(key)
                    for key in [
                        "volume_surge_1d_20", "volume_surge_5d_20", "volume_surge_1d_50", "volume_surge_5d_50",
                        "breakout_20d_pct", "trend_regime", "atr_pct", "squeeze_ratio", "squeeze_flag",
                        "gap_reversal_flag", "liquidity_spread_proxy", "rs_spy_20", "rs_qqq_20", "rank_reasons",
                    ]
                    if key in values
                }
                cur.execute(
                    """
                    INSERT INTO scanner_results(
                      run_id,ticker,score,data_date,close,r5,r20,r60,vs20,vs50,atr,avg_volume,
                      high20,low20,extension_penalty,liquidity_pass,notes
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(run_id, ticker) DO UPDATE SET
                      score=excluded.score, data_date=excluded.data_date, close=excluded.close,
                      r5=excluded.r5, r20=excluded.r20, r60=excluded.r60, notes=excluded.notes
                    """,
                    (
                        run_id,
                        ticker,
                        float(score),
                        _date(values.get("date")),
                        values.get("close"),
                        values.get("r5"),
                        values.get("r20"),
                        values.get("r60"),
                        values.get("vs20"),
                        values.get("vs50"),
                        values.get("atr"),
                        values.get("avgvol"),
                        values.get("hi20"),
                        values.get("lo20"),
                        values.get("extension_penalty"),
                        bool(values.get("liquidity_pass", True)),
                        _jsonb(factor_payload),
                    ),
                )
        conn.commit()
        return run_id


def persist_recommendation(ticket: Mapping[str, Any], validation: Mapping[str, Any], notes: Mapping[str, Any], dsn: str | None = None) -> int:
    """Persist a validated recommendation/watch row to Postgres primary."""
    with connect_postgres(dsn) as conn:
        ensure_operational_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO recommendations(
                  report_id,ticker,action,recommendation_type,thesis,setup_type,entry_zone,
                  entry_trigger,stop,target,risk_reward,confidence,position_size_suggestion,
                  holding_period,status,notes
                ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (
                    str(ticket.get("report_id")) if ticket.get("report_id") is not None else None,
                    ticket["ticker"],
                    ticket["action"] or "watch",
                    ticket["instrument_type"] or "watchlist",
                    ticket["thesis"],
                    ticket["setup"],
                    ticket.get("entry_zone"),
                    ticket["entry_trigger"],
                    ticket["stop_invalidation"],
                    ticket["target_exit"],
                    ticket["risk_reward"],
                    ticket["confidence"],
                    ticket["size_guidance"],
                    ticket["holding_period"],
                    validation["status"],
                    _jsonb(notes),
                ),
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("Postgres did not return recommendations.id")
            rec_id = int(row[0])
        conn.commit()
        return rec_id



def refresh_universe_cache_postgres(source_records: dict[str, list[dict]], dsn: str | None = None) -> int:
    """Upsert scanner universe records into Postgres primary."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    touched = 0
    with connect_postgres(dsn) as conn:
        ensure_operational_tables(conn)
        with conn.cursor() as cur:
            for source, records in source_records.items():
                for record in records:
                    symbol = str(record.get("symbol") or "").strip().upper().replace('.', '-')
                    if not symbol:
                        continue
                    cur.execute(
                        """
                        INSERT INTO universe_symbols(symbol,name,source,sector,is_etf,last_seen,active)
                        VALUES(%s,%s,%s,%s,%s,%s,true)
                        ON CONFLICT(symbol) DO UPDATE SET
                          name=COALESCE(excluded.name, universe_symbols.name),
                          source=CASE
                            WHEN universe_symbols.source LIKE '%%' || excluded.source || '%%' THEN universe_symbols.source
                            ELSE universe_symbols.source || ',' || excluded.source
                          END,
                          sector=COALESCE(excluded.sector, universe_symbols.sector),
                          is_etf=(universe_symbols.is_etf OR excluded.is_etf),
                          last_seen=excluded.last_seen,
                          active=true
                        """,
                        (symbol, record.get("name") or symbol, record.get("source") or source, record.get("sector"), bool(record.get("is_etf") or False), now),
                    )
                    touched += 1
        conn.commit()
    return touched


def load_universe_postgres(universe: str = "expanded", dsn: str | None = None) -> list[str]:
    with connect_postgres(dsn) as conn:
        ensure_operational_tables(conn)
        with conn.cursor() as cur:
            if universe == "core":
                cur.execute("SELECT symbol FROM universe_symbols WHERE active=true AND (source LIKE %s OR source LIKE %s) ORDER BY symbol", ("%core%", "%core_etf%"))
            elif universe == "etf":
                cur.execute("SELECT symbol FROM universe_symbols WHERE active=true AND is_etf=true ORDER BY symbol")
            elif universe == "expanded":
                cur.execute("SELECT symbol FROM universe_symbols WHERE active=true ORDER BY symbol")
            else:
                raise ValueError(f"unknown universe {universe!r}")
            return [r[0] for r in cur.fetchall()]

def latest_scanner_freshness() -> dict[str, Any]:
    with connect_postgres() as conn:
        ensure_operational_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.id, r.run_time, count(sr.id), max(sr.data_date)
                FROM scanner_runs r
                LEFT JOIN scanner_results sr ON sr.run_id=r.id
                WHERE r.id=(SELECT max(id) FROM scanner_runs)
                GROUP BY r.id, r.run_time
                """
            )
            row = cur.fetchone()
    if row is None:
        return {"backend": "postgres", "status": "scanner_stale", "reason": "no Postgres scanner run found"}
    return {"backend": "postgres", "latest_run_id": row[0], "latest_run_time": row[1].isoformat(), "candidate_count": row[2], "latest_data_date": row[3].isoformat() if row[3] else None}


def fallback_warning(component: str, reason: str) -> str:
    return (
        f"POSTGRES_PRIMARY_FALLBACK component={component}: {reason}. "
        "Using stale SQLite compatibility path only; do not create actionable recommendations unless Postgres freshness/risk gates are restored."
    )
