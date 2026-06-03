#!/usr/bin/env python3
"""Deterministic Hermes-EOD strategy seeding, signal generation, and approved gate.

This module is deliberately mechanical. It writes research/candidate/approved
strategy signals from price, feature, and earnings rows; it creates actionable
setup tickets only when the originating strategy is already human-approved.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, timedelta
from decimal import Decimal
from typing import Sequence

DEFAULT_DSN = os.environ.get("WOLFY_POSTGRES_DSN", "dbname=wolfy user=root host=/var/run/postgresql")
DEFAULT_STRATEGIES = (
    (
        "pead",
        "post_earnings_announcement_drift",
        {"source": "Hermes-EOD Section 3", "requires_backtest": True},
        "Seeded as research_only. Must pass walk-forward OOS and human approval before capital setups.",
    ),
    (
        "trend_volume_vol_regime",
        "trend_plus_volume_confirmation",
        {"source": "Hermes-EOD Section 3", "requires_volatility_regime_filter": True, "requires_backtest": True},
        "Seeded as research_only. Deterministic features/signals required; no LLM-generated edge.",
    ),
    (
        "sector_cross_sectional_momentum",
        "cross_sectional_momentum",
        {"source": "Hermes-EOD Section 3", "rebalance": "weekly", "requires_backtest": True},
        "Seeded as research_only. Human approval required for status promotion beyond candidate.",
    ),
)


def _json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def ensure_signal_schema(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS strategies (
          id serial PRIMARY KEY,
          name text UNIQUE,
          setup_type text,
          status text CHECK (status IN ('research_only','candidate','approved','retired')),
          latest_oos_sharpe numeric,
          latest_oos_verdict boolean,
          last_validated date,
          params jsonb,
          notes text
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_strategies_status ON strategies(status, setup_type)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS earnings_calendar (
          ticker text NOT NULL,
          event_dt date NOT NULL,
          session text,
          confirmed boolean,
          PRIMARY KEY (ticker, event_dt),
          CONSTRAINT earnings_calendar_session_check CHECK (session IS NULL OR session IN ('bmo', 'amc'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_earnings_calendar_event_dt ON earnings_calendar(event_dt, ticker)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS signals (
          ticker text NOT NULL,
          dt date NOT NULL,
          strategy_id int REFERENCES strategies(id),
          direction text,
          raw jsonb,
          PRIMARY KEY (ticker, dt, strategy_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_dt_strategy ON signals(dt, strategy_id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS setups (
          id serial PRIMARY KEY,
          created_dt date,
          for_session date,
          ticker text,
          strategy_id int REFERENCES strategies(id),
          direction text,
          liquidity_ok boolean,
          event_flag text,
          option_structure jsonb,
          iv_view jsonb,
          size jsonb,
          invalidation numeric,
          thesis text,
          falsification text,
          confidence numeric,
          rank int,
          status text DEFAULT 'proposed',
          CONSTRAINT setups_status_check CHECK (status IN ('proposed','pending_review','taken','skipped','expired','rejected'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_setups_for_session_status ON setups(for_session, status, rank)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_setups_ticker_created ON setups(ticker, created_dt DESC)")
    conn.execute("ALTER TABLE features ADD COLUMN IF NOT EXISTS liquidity boolean")


def seed_default_strategies(conn) -> dict:
    """Insert the three EOD research strategies without auto-approval."""
    ensure_signal_schema(conn)
    upserted = 0
    for name, setup_type, params, notes in DEFAULT_STRATEGIES:
        conn.execute(
            """
            INSERT INTO strategies(name, setup_type, status, params, notes)
            VALUES (%s, %s, 'research_only', %s::jsonb, %s)
            ON CONFLICT (name) DO UPDATE SET
              setup_type=EXCLUDED.setup_type,
              params=EXCLUDED.params,
              notes=EXCLUDED.notes
            """,
            (name, setup_type, _json(params), notes),
        )
        upserted += 1
    return {"strategies_seeded": upserted, "default_status": "research_only"}


def _strategy_ids(conn) -> dict[str, tuple[int, str]]:
    rows = conn.execute("SELECT id, name, status FROM strategies WHERE name = ANY(%s)", ([s[0] for s in DEFAULT_STRATEGIES],)).fetchall()
    return {str(name): (int(strategy_id), str(status)) for strategy_id, name, status in rows}


def _upsert_signal(conn, *, ticker: str, signal_dt: date, strategy_id: int, direction: str, raw: dict) -> None:
    conn.execute(
        """
        INSERT INTO signals(ticker, dt, strategy_id, direction, raw)
        VALUES (%s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (ticker, dt, strategy_id) DO UPDATE SET
          direction=EXCLUDED.direction,
          raw=EXCLUDED.raw
        """,
        (ticker.upper(), signal_dt, strategy_id, direction, _json(raw)),
    )


def _generate_pead(conn, *, tickers: Sequence[str], signal_dt: date, strategies: dict[str, tuple[int, str]]) -> int:
    strategy_id, status = strategies["pead"]
    rows = conn.execute(
        """
        SELECT ec.ticker, ec.event_dt, ec.session
        FROM earnings_calendar ec
        JOIN prices p ON p.ticker=ec.ticker AND p.dt=%s
        LEFT JOIN features f ON f.ticker=ec.ticker AND f.dt=%s
        WHERE ec.ticker = ANY(%s)
          AND ec.event_dt BETWEEN %s AND %s
          AND coalesce(ec.confirmed, true) = true
          AND coalesce(f.liquidity, true) = true
        ORDER BY ec.ticker
        """,
        (signal_dt, signal_dt, [t.upper() for t in tickers], signal_dt - timedelta(days=3), signal_dt),
    ).fetchall()
    for ticker, event_dt, session in rows:
        _upsert_signal(
            conn,
            ticker=ticker,
            signal_dt=signal_dt,
            strategy_id=strategy_id,
            direction="long",
            raw={"strategy": "pead", "event_dt": event_dt, "session": session, "gate_status": status, "reason": "post-earnings EOD drift research signal"},
        )
    return len(rows)


def _generate_trend_volume(conn, *, tickers: Sequence[str], signal_dt: date, strategies: dict[str, tuple[int, str]]) -> int:
    strategy_id, status = strategies["trend_volume_vol_regime"]
    rows = conn.execute(
        """
        SELECT p.ticker, p.close, f.sma_fast, f.sma_slow, f.vol_ratio, f.vol_regime, f.atr
        FROM prices p
        JOIN features f ON f.ticker=p.ticker AND f.dt=p.dt
        WHERE p.ticker = ANY(%s) AND p.dt=%s
          AND f.sma_fast IS NOT NULL AND f.sma_slow IS NOT NULL
          AND p.close > f.sma_fast AND f.sma_fast > f.sma_slow
          AND coalesce(f.vol_ratio, 0) >= 1.2
          AND coalesce(f.vol_regime, 'unknown') IN ('normal', 'high')
          AND coalesce(f.liquidity, true) = true
        ORDER BY p.ticker
        """,
        ([t.upper() for t in tickers], signal_dt),
    ).fetchall()
    for ticker, close, sma_fast, sma_slow, vol_ratio, vol_regime, atr in rows:
        _upsert_signal(
            conn,
            ticker=ticker,
            signal_dt=signal_dt,
            strategy_id=strategy_id,
            direction="long",
            raw={
                "strategy": "trend_volume_vol_regime",
                "close": close,
                "sma_fast": sma_fast,
                "sma_slow": sma_slow,
                "vol_ratio": vol_ratio,
                "vol_regime": vol_regime,
                "atr": atr,
                "gate_status": status,
                "reason": "close above fast/slow trend with volume confirmation and acceptable volatility regime",
            },
        )
    return len(rows)


def _generate_momentum(conn, *, tickers: Sequence[str], signal_dt: date, momentum_lookback_days: int, momentum_top_n: int, strategies: dict[str, tuple[int, str]]) -> int:
    strategy_id, status = strategies["sector_cross_sectional_momentum"]
    candidates: list[dict] = []
    for ticker in [t.upper() for t in tickers]:
        row = conn.execute(
            """
            SELECT cur.close, prev.close
            FROM prices cur
            JOIN LATERAL (
              SELECT close FROM prices
              WHERE ticker=cur.ticker AND dt <= %s
              ORDER BY dt DESC LIMIT 1
            ) prev ON true
            LEFT JOIN features f ON f.ticker=cur.ticker AND f.dt=cur.dt
            WHERE cur.ticker=%s AND cur.dt=%s AND coalesce(f.liquidity, true)=true
            """,
            (signal_dt - timedelta(days=momentum_lookback_days), ticker, signal_dt),
        ).fetchone()
        if not row or row[1] in (None, 0):
            continue
        score = (Decimal(str(row[0])) / Decimal(str(row[1]))) - Decimal("1")
        if score > 0:
            candidates.append({"ticker": ticker, "score": score, "close": row[0], "lookback_close": row[1]})
    candidates.sort(key=lambda item: item["score"], reverse=True)
    selected = candidates[: max(0, momentum_top_n)]
    for rank, item in enumerate(selected, start=1):
        _upsert_signal(
            conn,
            ticker=item["ticker"],
            signal_dt=signal_dt,
            strategy_id=strategy_id,
            direction="long",
            raw={
                "strategy": "sector_cross_sectional_momentum",
                "rank": rank,
                "momentum_return": item["score"],
                "close": item["close"],
                "lookback_close": item["lookback_close"],
                "lookback_days": momentum_lookback_days,
                "gate_status": status,
                "reason": "positive top-bucket cross-sectional EOD momentum research signal",
            },
        )
    return len(selected)


def generate_eod_signals(
    conn,
    *,
    tickers: Sequence[str],
    signal_dt: date,
    momentum_lookback_days: int = 63,
    momentum_top_n: int = 10,
) -> dict:
    if not tickers:
        raise ValueError("tickers are required")
    seed_default_strategies(conn)
    strategies = _strategy_ids(conn)
    counts = {
        "pead": _generate_pead(conn, tickers=tickers, signal_dt=signal_dt, strategies=strategies),
        "trend_volume_vol_regime": _generate_trend_volume(conn, tickers=tickers, signal_dt=signal_dt, strategies=strategies),
        "sector_cross_sectional_momentum": _generate_momentum(
            conn,
            tickers=tickers,
            signal_dt=signal_dt,
            momentum_lookback_days=momentum_lookback_days,
            momentum_top_n=momentum_top_n,
            strategies=strategies,
        ),
    }
    return {"signal_dt": signal_dt.isoformat(), "signals_by_strategy": counts, "signals_upserted": sum(counts.values())}


def _raw_value(raw: object, key: str, default: object = None) -> object:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return default


def propose_approved_setups(conn, *, signal_dt: date, for_session: date, tickers: Sequence[str] | None = None, max_setups: int = 10) -> dict:
    ensure_signal_schema(conn)
    params: list[object] = [signal_dt]
    ticker_clause = ""
    if tickers is not None:
        ticker_clause = "AND s.ticker = ANY(%s)"
        params.append([t.upper() for t in tickers])
    rows = conn.execute(
        f"""
        SELECT s.ticker, s.direction, s.raw, st.id, st.name, st.status, p.close, f.atr, f.liquidity
        FROM signals s
        JOIN strategies st ON st.id=s.strategy_id
        JOIN prices p ON p.ticker=s.ticker AND p.dt=s.dt
        LEFT JOIN features f ON f.ticker=s.ticker AND f.dt=s.dt
        WHERE s.dt=%s {ticker_clause}
          AND lower(coalesce(s.direction,'')) IN ('long','buy')
        ORDER BY CASE WHEN st.status='approved' THEN 0 ELSE 1 END, s.ticker, st.name
        """,
        params,
    ).fetchall()
    created = 0
    blocked = 0
    rank = 1
    for ticker, direction, raw, strategy_id, strategy_name, status, close, atr, liquidity in rows:
        if status != "approved":
            blocked += 1
            continue
        if created >= max_setups:
            break
        close_dec = Decimal(str(close))
        atr_dec = Decimal(str(atr)) if atr is not None else close_dec * Decimal("0.03")
        invalidation = close_dec - (atr_dec * Decimal("2"))
        thesis = f"{ticker} has an approved deterministic EOD signal from {strategy_name}; FACT: signal_dt={signal_dt}, close={close}, strategy_status=approved. JUDGMENT: pending_review setup for next-session human/Sentinel review."
        falsification = "Invalidate if the next-session price breaks the ATR-based stop or deterministic EOD signal/risk gates fail before execution."
        conn.execute(
            """
            INSERT INTO setups(created_dt, for_session, ticker, strategy_id, direction, liquidity_ok, event_flag, option_structure, iv_view, size, invalidation, thesis, falsification, confidence, rank, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,'pending_review')
            """,
            (
                signal_dt,
                for_session,
                ticker,
                strategy_id,
                direction,
                bool(liquidity) if liquidity is not None else True,
                str(_raw_value(raw, "strategy", strategy_name)),
                _json({"allowed": "defined_risk_only", "selected": None}),
                _json({"source": "not_evaluated", "action": "do_not_infer_iv"}),
                _json({"paper_account_usd": 5000, "risk_fraction": "0.01", "max_concurrent_positions": 3}),
                invalidation,
                thesis,
                falsification,
                Decimal("0.55"),
                rank,
            ),
        )
        created += 1
        rank += 1
    return {"signal_dt": signal_dt.isoformat(), "for_session": for_session.isoformat(), "setups_created": created, "blocked_by_strategy_status": blocked}


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic Wolfy EOD signals and approved-gated setups")
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    parser.add_argument("--tickers", required=True, help="Comma-separated tickers")
    parser.add_argument("--signal-dt", required=True)
    parser.add_argument("--for-session")
    parser.add_argument("--create-setups", action="store_true")
    parser.add_argument("--momentum-lookback-days", type=int, default=63)
    parser.add_argument("--momentum-top-n", type=int, default=10)
    args = parser.parse_args(argv)
    import psycopg

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    signal_dt = _parse_date(args.signal_dt)
    with psycopg.connect(args.dsn) as conn:
        result = generate_eod_signals(conn, tickers=tickers, signal_dt=signal_dt, momentum_lookback_days=args.momentum_lookback_days, momentum_top_n=args.momentum_top_n)
        if args.create_setups:
            for_session = _parse_date(args.for_session) if args.for_session else signal_dt + timedelta(days=1)
            result["approved_gate"] = propose_approved_setups(conn, signal_dt=signal_dt, for_session=for_session, tickers=tickers)
        print(json.dumps(result, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
