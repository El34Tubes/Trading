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
from typing import Any, Mapping, Sequence

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
    (
        "liquid_rs_breakout_continuation",
        "rs_breakout_continuation",
        {
            "source": "Wolfy user-directed recommendation engine",
            "requires_backtest": True,
            "breakout_lookback_days": 5,
            "rs_benchmark": "SPY",
            "rs_window_days": 20,
            "min_vol_ratio": "1.2",
            "near_high_pct": "0.05",
            "stop_rule": "prior_5_day_low",
            "max_hold_days": 10,
            "preferred_instrument": "2-3wk slightly OTM call spread",
            "option_liquidity_hard_gate": False,
        },
        "Seeded as research_only. Human approval required before recommendations; deterministic 5-day RS breakout setup for options-oriented paper candidates.",
    ),
    (
        "liquid_rs_breakout_tight_risk_volume",
        "rs_breakout_continuation",
        {
            "source": "Wolfy failed-validation revision 2026-07-30",
            "parent_strategy": "liquid_rs_breakout_continuation",
            "requires_backtest": True,
            "breakout_lookback_days": 5,
            "rs_benchmark": "SPY",
            "rs_window_days": 20,
            "min_vol_ratio": "2.0",
            "min_rs_excess_20d": "0.02",
            "max_stop_risk_pct": "0.04",
            "near_high_pct": "0.05",
            "stop_rule": "prior_5_day_low",
            "max_hold_days": 10,
            "preferred_instrument": "2-3wk slightly OTM call spread",
            "option_liquidity_hard_gate": False,
        },
        "Tighter research_only revision after backward setup-success analysis: high volume, positive RS excess, and stop distance <=4%.",
    ),
    (
        "liquid_rs_breakout_close_confirm_1r",
        "rs_breakout_continuation",
        {
            "source": "Wolfy exhaustive setup-outcome grid 2026-08-03",
            "parent_strategy": "liquid_rs_breakout_continuation",
            "requires_backtest": True,
            "breakout_lookback_days": 5,
            "rs_benchmark": "SPY",
            "rs_window_days": 20,
            "min_vol_ratio": "1.2",
            "min_rs_excess_20d": "0.02",
            "max_prior_low_risk_pct": "0.05",
            "market_regime": "SPY_above_50_sma",
            "stop_rule": "close_below_breakout_level",
            "target_r": "1.0",
            "max_hold_days": 10,
            "preferred_instrument": "2-3wk slightly OTM call spread",
            "option_liquidity_hard_gate": False,
        },
        "Research_only revision from exhaustive grid: SPY>50, 1R target, close-back-below-breakout invalidation, RS excess >=2%, volume >=1.2, prior-low risk <=5%.",
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
          notes text,
          metadata jsonb,
          description text
        )
        """
    )
    conn.execute("ALTER TABLE strategies ADD COLUMN IF NOT EXISTS metadata jsonb")
    conn.execute("ALTER TABLE strategies ADD COLUMN IF NOT EXISTS description text")
    conn.execute("UPDATE strategies SET metadata=COALESCE(metadata, params, '{}'::jsonb) WHERE metadata IS NULL")
    conn.execute("UPDATE strategies SET description=notes WHERE description IS NULL AND notes IS NOT NULL")
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS config (
          key text PRIMARY KEY,
          value jsonb NOT NULL,
          updated_at timestamptz DEFAULT now()
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS positions (
          id serial PRIMARY KEY,
          ticker text,
          opened date,
          structure jsonb,
          risk_amount numeric,
          invalidation numeric,
          status text
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_status_ticker ON positions(status, ticker)")


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


def recommendation_universe_tickers(conn, *, signal_dt: date, min_history_bars: int = 20) -> list[str]:
    """Return broad/current recommendation tickers with deterministic data-readiness gates.

    This intentionally does not restrict by Wolfy tier. The user's first
    recommendation engine may consider the whole active universe, but a ticker
    must have current price/features rows and enough stored bars for the
    strategy window before it can enter signal generation.
    """
    ensure_signal_schema(conn)
    rows = conn.execute(
        """
        SELECT u.symbol
        FROM universe u
        JOIN prices p ON p.ticker=u.symbol AND p.dt=%s
        JOIN features f ON f.ticker=u.symbol AND f.dt=%s
        JOIN LATERAL (
          SELECT count(*) AS bar_count
          FROM prices ph
          WHERE ph.ticker=u.symbol AND ph.dt <= %s
        ) hist ON true
        WHERE coalesce(u.active, true)=true
          AND coalesce(u.enabled, true)=true
          AND hist.bar_count >= %s
          AND p.close IS NOT NULL
          AND f.atr IS NOT NULL
          AND f.vol_ratio IS NOT NULL
        ORDER BY u.symbol
        """,
        (signal_dt, signal_dt, signal_dt, min_history_bars),
    ).fetchall()
    return [str(row[0]).upper() for row in rows]


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


def _generate_liquid_rs_breakout(
    conn,
    *,
    tickers: Sequence[str],
    signal_dt: date,
    strategies: dict[str, tuple[int, str]],
    breakout_lookback_days: int = 5,
    rs_window_days: int = 20,
    min_vol_ratio: Decimal = Decimal("1.2"),
    min_rs_excess: Decimal = Decimal("0"),
    max_stop_risk_pct: Decimal | None = None,
    near_high_pct: Decimal = Decimal("0.05"),
    strategy_name: str = "liquid_rs_breakout_continuation",
    require_spy_above_sma_days: int | None = None,
    stop_rule: str = "prior_5_day_low",
    target_r: Decimal = Decimal("1.5"),
) -> int:
    strategy_id, status = strategies[strategy_name]
    spy_row = conn.execute(
        """
        SELECT cur.close, prev.close
        FROM prices cur
        JOIN LATERAL (
          SELECT close FROM prices
          WHERE ticker='SPY' AND dt <= %s
          ORDER BY dt DESC LIMIT 1
        ) prev ON true
        WHERE cur.ticker='SPY' AND cur.dt=%s
        """,
        (signal_dt - timedelta(days=rs_window_days), signal_dt),
    ).fetchone()
    if not spy_row or spy_row[1] in (None, 0):
        return 0
    spy_return = (Decimal(str(spy_row[0])) / Decimal(str(spy_row[1]))) - Decimal("1")
    spy_sma = None
    if require_spy_above_sma_days:
        spy_sma_row = conn.execute(
            """
            SELECT avg(close) FROM (
              SELECT close FROM prices WHERE ticker='SPY' AND dt <= %s ORDER BY dt DESC LIMIT %s
            ) spy_window
            """,
            (signal_dt, require_spy_above_sma_days),
        ).fetchone()
        spy_sma = Decimal(str(spy_sma_row[0])) if spy_sma_row and spy_sma_row[0] is not None else None
        if spy_sma is None or Decimal(str(spy_row[0])) <= spy_sma:
            return 0

    generated = 0
    for ticker in [t.upper() for t in tickers if t.upper() != "SPY"]:
        row = conn.execute(
            """
            SELECT p.close, p.high, f.sma_fast, f.sma_slow, f.vol_ratio, f.atr, f.liquidity,
                   prev.close,
                   prior.prior_high, prior.prior_low
            FROM prices p
            JOIN LATERAL (
              SELECT close FROM prices
              WHERE ticker=p.ticker AND dt <= %s
              ORDER BY dt DESC LIMIT 1
            ) prev ON true
            JOIN LATERAL (
              SELECT max(high) AS prior_high, min(low) AS prior_low
              FROM (
                SELECT high, low FROM prices
                WHERE ticker=p.ticker AND dt < p.dt
                ORDER BY dt DESC LIMIT %s
              ) recent
            ) prior ON true
            LEFT JOIN features f ON f.ticker=p.ticker AND f.dt=p.dt
            WHERE p.ticker=%s AND p.dt=%s
              AND coalesce(f.liquidity, true)=true
              AND f.vol_ratio IS NOT NULL
              AND f.atr IS NOT NULL
            """,
            (signal_dt - timedelta(days=rs_window_days), breakout_lookback_days, ticker, signal_dt),
        ).fetchone()
        if not row:
            continue
        close, high, sma_fast, sma_slow, vol_ratio, atr, _liquidity, lookback_close, prior_high, prior_low = row
        if lookback_close in (None, 0) or prior_high is None or prior_low is None:
            continue
        close_dec = Decimal(str(close))
        high_dec = Decimal(str(high))
        prior_high_dec = Decimal(str(prior_high))
        prior_low_dec = Decimal(str(prior_low))
        vol_ratio_dec = Decimal(str(vol_ratio))
        ticker_return = (close_dec / Decimal(str(lookback_close))) - Decimal("1")
        rs_excess = ticker_return - spy_return
        recent_high = max(high_dec, prior_high_dec)
        within_5pct_recent_high = close_dec >= (recent_high * (Decimal("1") - near_high_pct))
        trend_ok = True
        if sma_fast is not None:
            trend_ok = trend_ok and close_dec > Decimal(str(sma_fast))
        if sma_fast is not None and sma_slow is not None:
            trend_ok = trend_ok and Decimal(str(sma_fast)) >= Decimal(str(sma_slow))

        if not trend_ok:
            continue
        if close_dec <= prior_high_dec:
            continue
        if ticker_return <= spy_return:
            continue
        if rs_excess < min_rs_excess:
            continue
        if vol_ratio_dec < min_vol_ratio:
            continue
        stop_risk_pct = (close_dec - prior_low_dec) / close_dec if close_dec else None
        if max_stop_risk_pct is not None and (stop_risk_pct is None or stop_risk_pct > max_stop_risk_pct):
            continue
        if not within_5pct_recent_high:
            continue

        raw = {
            "strategy": strategy_name,
            "close": close_dec,
            "prior_5d_high": prior_high_dec,
            "prior_5d_low": prior_low_dec,
            "sma_fast": sma_fast,
            "sma_slow": sma_slow,
            "atr": atr,
            "atr_pct": Decimal(str(atr)) / close_dec if close_dec else None,
            "ticker_return_20d": ticker_return,
            "spy_return_20d": spy_return,
            "rs_excess_20d": rs_excess,
            "min_rs_excess_20d": min_rs_excess,
            "vol_ratio": vol_ratio_dec,
            "min_vol_ratio": min_vol_ratio,
            "stop_risk_pct": stop_risk_pct,
            "max_stop_risk_pct": max_stop_risk_pct,
            "spy_sma_days": require_spy_above_sma_days,
            "spy_sma": spy_sma,
            "within_5pct_recent_high": within_5pct_recent_high,
            "stop_rule": stop_rule,
            "invalidation": prior_low_dec if stop_rule == "prior_5_day_low" else prior_high_dec,
            "max_hold_days": 10,
            "target_r": target_r,
            "profit_plan": f"take_partial_or_review_at_{target_r}R_then_trail_remainder",
            "preferred_instrument": "2-3wk slightly OTM call spread",
            "option_liquidity_hard_gate": False,
            "option_liquidity_note": "user_to_evaluate_manually",
            "gap_no_chase_atr": Decimal("0.5"),
            "gate_status": status,
            "reason": "20d RS leader breaking prior 5d high on confirmed volume near highs",
        }
        _upsert_signal(conn, ticker=ticker, signal_dt=signal_dt, strategy_id=strategy_id, direction="long", raw=raw)
        generated += 1
    return generated


def generate_eod_signals(
    conn,
    *,
    tickers: Sequence[str] | None,
    signal_dt: date,
    momentum_lookback_days: int = 63,
    momentum_top_n: int = 10,
) -> dict:
    universe_source = "explicit_tickers"
    if tickers is None:
        tickers = recommendation_universe_tickers(conn, signal_dt=signal_dt)
        universe_source = "broad_current_with_data_gates"
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
        "liquid_rs_breakout_continuation": _generate_liquid_rs_breakout(conn, tickers=tickers, signal_dt=signal_dt, strategies=strategies),
        "liquid_rs_breakout_tight_risk_volume": _generate_liquid_rs_breakout(
            conn,
            tickers=tickers,
            signal_dt=signal_dt,
            strategies=strategies,
            strategy_name="liquid_rs_breakout_tight_risk_volume",
            min_vol_ratio=Decimal("2.0"),
            min_rs_excess=Decimal("0.02"),
            max_stop_risk_pct=Decimal("0.04"),
        ),
        "liquid_rs_breakout_close_confirm_1r": _generate_liquid_rs_breakout(
            conn,
            tickers=tickers,
            signal_dt=signal_dt,
            strategies=strategies,
            strategy_name="liquid_rs_breakout_close_confirm_1r",
            min_vol_ratio=Decimal("1.2"),
            min_rs_excess=Decimal("0.02"),
            max_stop_risk_pct=Decimal("0.05"),
            require_spy_above_sma_days=50,
            stop_rule="close_below_breakout_level",
            target_r=Decimal("1.0"),
        ),
    }
    return {
        "signal_dt": signal_dt.isoformat(),
        "universe_source": universe_source,
        "tickers_considered": [t.upper() for t in tickers],
        "signals_by_strategy": counts,
        "signals_upserted": sum(counts.values()),
    }


def _raw_value(raw: object, key: str, default: object = None) -> object:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return default


def _as_decimal(value: Any, default: Decimal) -> Decimal:
    if value is None:
        return default
    return Decimal(str(value))


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _config_values(conn) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT key, value
        FROM config
        WHERE key IN ('risk_per_trade','max_portfolio_heat','max_name_weight','max_drawdown_killswitch','max_adv_frac')
        """
    ).fetchall()
    return {str(key): value for key, value in rows}


def _config_fraction(config: Mapping[str, Any], key: str, nested_key: str, default: str) -> Decimal:
    value = config.get(key)
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, Mapping):
        return _as_decimal(value.get(nested_key), Decimal(default))
    return Decimal(default)


def _event_landmines(conn, ticker: str, *, start: date, horizon_days: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT event_dt, session, confirmed
        FROM earnings_calendar
        WHERE ticker=%s AND event_dt >= %s AND event_dt <= %s
        ORDER BY event_dt
        """,
        (ticker, start, start + timedelta(days=horizon_days)),
    ).fetchall()
    return [{"event_dt": row[0], "session": row[1], "confirmed": row[2]} for row in rows]


def _open_position_risk(conn) -> tuple[int, Decimal, dict[str, Decimal]]:
    rows = conn.execute(
        """
        SELECT ticker, risk_amount
        FROM positions
        WHERE lower(coalesce(status,'')) IN ('open','taken','active')
        """
    ).fetchall()
    by_ticker: dict[str, Decimal] = {}
    total = Decimal("0")
    for ticker, risk_amount in rows:
        risk = _as_decimal(risk_amount, Decimal("0"))
        total += risk
        by_ticker[str(ticker).upper()] = by_ticker.get(str(ticker).upper(), Decimal("0")) + risk
    return len(rows), total, by_ticker


def _instrument_context(screening_context: Mapping[str, Any], ticker: str) -> Mapping[str, Any]:
    instruments = screening_context.get("instruments", {}) if isinstance(screening_context, Mapping) else {}
    if isinstance(instruments, Mapping):
        item = instruments.get(ticker.upper()) or instruments.get(ticker) or {}
        if isinstance(item, Mapping):
            return item
    return {}


def _build_screened_setup(
    *,
    ticker: str,
    direction: str,
    raw: Any,
    strategy_id: int,
    strategy_name: str,
    close: Any,
    atr: Any,
    liquidity: Any,
    dollar_vol: Any,
    config: Mapping[str, Any],
    screening_context: Mapping[str, Any],
    signal_dt: date,
    for_session: date,
    current_open_positions: int,
    current_heat: Decimal,
) -> tuple[dict[str, Any], list[str]]:
    reasons: list[str] = []
    close_dec = Decimal(str(close))
    atr_dec = Decimal(str(atr)) if atr is not None else close_dec * Decimal("0.03")
    invalidation = close_dec - (atr_dec * Decimal("2"))
    risk_per_share = max(close_dec - invalidation, Decimal("0.01"))

    account_equity = _as_decimal(screening_context.get("account_equity_usd"), Decimal("5000"))
    risk_fraction = _config_fraction(config, "risk_per_trade", "fraction_of_equity", "0.01")
    max_heat_fraction = _config_fraction(config, "max_portfolio_heat", "fraction_of_equity", "0.03")
    max_name_fraction = _config_fraction(config, "max_name_weight", "fraction_of_equity", "0.20")
    max_drawdown_fraction = _config_fraction(config, "max_drawdown_killswitch", "fraction_of_equity", "0.10")
    max_adv_fraction = _config_fraction(config, "max_adv_frac", "fraction_of_average_daily_volume", "0.02")
    max_positions = int(screening_context.get("max_concurrent_positions", 3))

    risk_amount = account_equity * risk_fraction
    qty = risk_amount / risk_per_share
    notional = qty * close_dec
    avg_dollar_vol = _as_decimal(dollar_vol, Decimal("0"))
    avg_volume = avg_dollar_vol / close_dec if close_dec else Decimal("0")

    if liquidity is False:
        reasons.append("liquidity gate failed")
    if avg_dollar_vol and qty > (avg_volume * max_adv_fraction):
        reasons.append("ADV fraction gate failed")

    events = _event_landmines(screening_context["conn"], ticker, start=for_session, horizon_days=int(screening_context.get("event_horizon_days", 1)))
    if events:
        reasons.append("event landmine inside setup horizon")

    drawdown = _as_decimal(screening_context.get("current_drawdown_fraction"), Decimal("0"))
    if drawdown >= max_drawdown_fraction:
        reasons.append("drawdown kill switch active")
    if current_open_positions >= max_positions:
        reasons.append("max concurrent positions breaker active")
    if current_heat + risk_amount > account_equity * max_heat_fraction:
        reasons.append("max portfolio heat breaker active")
    if notional > account_equity * max_name_fraction:
        reasons.append("max name weight breaker active")

    instrument = _instrument_context(screening_context, ticker)
    instrument_type = str(instrument.get("instrument_type", "equity")).lower()
    option_structure = {"instrument_type": instrument_type, "allowed": "defined_risk_only", "selected": None}
    iv_view = instrument.get("iv_view", {"source": "not_evaluated", "action": "do_not_infer_iv"})
    if instrument_type in {"option", "options", "call", "put"}:
        if instrument.get("option_liquidity_ok") is not True:
            reasons.append("option liquidity gate failed")
        if instrument.get("defined_risk") is not True:
            reasons.append("defined-risk option structure required")
        if isinstance(iv_view, Mapping) and iv_view.get("aligned") is not True:
            reasons.append("IV-vs-view gate failed")
        option_structure.update({"selected": instrument.get("structure"), "defined_risk": bool(instrument.get("defined_risk"))})

    size = {
        "paper_account_usd": _money(account_equity),
        "risk_fraction": str(risk_fraction),
        "risk_amount_usd": _money(risk_amount),
        "estimated_qty": str(qty.quantize(Decimal("0.0001"))),
        "notional_usd": _money(notional),
        "max_concurrent_positions": max_positions,
    }
    setup = {
        "ticker": ticker,
        "strategy_id": strategy_id,
        "strategy_name": strategy_name,
        "direction": direction,
        "liquidity_ok": bool(liquidity) if liquidity is not None else True,
        "event_flag": str(_raw_value(raw, "strategy", strategy_name)),
        "option_structure": option_structure,
        "iv_view": iv_view,
        "size": size,
        "invalidation": str(invalidation.quantize(Decimal("0.01"))),
        "confidence": Decimal("0.55"),
        "thesis": f"{ticker} has an approved deterministic EOD signal from {strategy_name}; FACT: signal_dt={signal_dt}, close={close}, strategy_status=approved, risk_amount={size['risk_amount_usd']}. JUDGMENT: pending_review setup for next-session human/Sentinel review after all deterministic gates pass.",
        "falsification": "Invalidate if the next-session price breaks the ATR-based stop or any deterministic EOD risk gate fails before execution.",
        "score": Decimal("0.55"),
    }
    return setup, reasons


def _recommendation_score(raw: Mapping[str, Any]) -> Decimal:
    return _as_decimal(_raw_value(raw, "rs_excess_20d"), Decimal("0")) * Decimal("100") + _as_decimal(_raw_value(raw, "vol_ratio"), Decimal("0"))


def write_approved_paper_recommendations(
    conn,
    *,
    signal_dt: date,
    tickers: Sequence[str] | None = None,
    max_recommendations: int = 3,
    risk_fraction: Decimal = Decimal("0.05"),
    dry_run: bool = False,
) -> dict:
    """Write approved-strategy deterministic paper recommendations to Postgres.

    This is paper-only: no broker execution and no paper_trades insert. The paper
    logging step is a separate gate. Recommendations are sourced only from
    strategies with status='approved'.
    """
    ensure_signal_schema(conn)
    params: list[object] = [signal_dt]
    ticker_clause = ""
    if tickers is not None:
        ticker_clause = "AND s.ticker = ANY(%s)"
        params.append([ticker.upper() for ticker in tickers])
    rows = conn.execute(
        f"""
        SELECT s.ticker, s.direction, s.raw, st.id, st.name, st.status, st.metadata
        FROM signals s
        JOIN strategies st ON st.id=s.strategy_id
        WHERE s.dt=%s {ticker_clause}
          AND lower(coalesce(s.direction,'')) IN ('long','buy')
        ORDER BY s.ticker, st.name
        """,
        params,
    ).fetchall()
    approved: list[dict[str, Any]] = []
    blocked_by_strategy_status = 0
    for ticker, direction, raw, strategy_id, strategy_name, status, metadata in rows:
        strategy_metadata = metadata if isinstance(metadata, Mapping) else {}
        if status != "approved" or strategy_metadata.get("approval_scope") != "paper_only_no_live_execution" or strategy_metadata.get("paper_recommendation_approval") is not True:
            blocked_by_strategy_status += 1
            continue
        raw_dict = raw if isinstance(raw, Mapping) else json.loads(raw or "{}")
        approved.append(
            {
                "ticker": str(ticker),
                "direction": str(direction or "long"),
                "raw": raw_dict,
                "strategy_id": int(strategy_id),
                "strategy_name": str(strategy_name),
                "score": _recommendation_score(raw_dict),
            }
        )
    approved.sort(key=lambda item: (-item["score"], item["ticker"]))
    selected = approved[: max(0, max_recommendations)]
    created = 0
    skipped_existing = 0
    serializable: list[dict[str, Any]] = []
    for item in selected:
        raw = item["raw"]
        ticker = item["ticker"]
        entry = _as_decimal(_raw_value(raw, "close"), Decimal("0"))
        invalidation = _as_decimal(_raw_value(raw, "invalidation"), _as_decimal(_raw_value(raw, "prior_5d_high"), Decimal("0")))
        risk_per_share = max(entry - invalidation, Decimal("0.01"))
        target_r = _as_decimal(_raw_value(raw, "target_r"), Decimal("1.0"))
        target = entry + risk_per_share * target_r
        notes = {
            "paper_only": True,
            "no_live_execution": True,
            "review_gate_required": False,
            "sentinel_yang_required": False,
            "paper_entry_baseline": "eod_close",
            "signal_dt": signal_dt.isoformat(),
            "strategy_id": item["strategy_id"],
            "strategy_name": item["strategy_name"],
            "source_signal": {k: (str(v) if isinstance(v, Decimal) else v) for k, v in raw.items()},
            "option_spread": {
                "structure": _raw_value(raw, "preferred_instrument", "2-3wk slightly OTM call spread"),
                "exact_contract": None,
                "liquidity_hard_gate": False,
                "user_evaluates_liquidity_manually": True,
            },
            "equity_fallback": True,
            "future_same_gate_auto_activation_allowed": True,
        }
        exists = conn.execute(
            """
            SELECT id FROM recommendations
            WHERE ticker=%s
              AND notes->>'signal_dt'=%s
              AND notes->>'strategy_name'=%s
              AND status IN ('paper_candidate','paper_logged')
            LIMIT 1
            """,
            (ticker, signal_dt.isoformat(), item["strategy_name"]),
        ).fetchone()
        payload = {
            "ticker": ticker,
            "strategy_name": item["strategy_name"],
            "entry": _money(entry),
            "stop": _money(invalidation),
            "target": _money(target),
            "risk_fraction": str(risk_fraction),
        }
        if exists:
            skipped_existing += 1
            serializable.append({**payload, "status": "existing"})
            continue
        if not dry_run:
            conn.execute(
                """
                INSERT INTO recommendations(ticker, action, recommendation_type, thesis, setup_type, entry_zone, entry_trigger, stop, target, risk_reward, confidence, position_size_suggestion, holding_period, status, notes)
                VALUES (%s,'buy','equity_plus_option_spread_when_data_exists',%s,%s,%s,%s,%s,%s,%s,'medium-high',%s,%s,'paper_candidate',%s::jsonb)
                """,
                (
                    ticker,
                    f"{ticker} triggered approved deterministic {item['strategy_name']} paper setup; paper-only, no live execution.",
                    item["strategy_name"],
                    f"EOD close baseline near {_money(entry)}",
                    f"Use EOD close baseline {_money(entry)} from {signal_dt.isoformat()} for paper accounting.",
                    f"Close below breakout/invalidation level {_money(invalidation)}.",
                    f"Initial paper target near {_money(target)} ({target_r}R); max hold 10 trading days.",
                    f"{target_r}R",
                    f"Paper risk {risk_fraction * Decimal('100'):.2f}% of account; no max-open cap for paper testing.",
                    "Up to 10 trading days",
                    _json(notes),
                ),
            )
        created += 1
        serializable.append({**payload, "status": "paper_candidate"})
    return {
        "signal_dt": signal_dt.isoformat(),
        "dry_run": dry_run,
        "recommendations_created": created if not dry_run else 0,
        "recommendations_ranked": len(selected),
        "skipped_existing": skipped_existing,
        "blocked_by_strategy_status": blocked_by_strategy_status,
        "paper_trades_created": 0,
        "recommendations": serializable,
    }


def _decimal_from_money(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default
    text = str(value).replace("$", "").replace(",", "").strip()
    if not text:
        return default
    try:
        return Decimal(text)
    except Exception:
        return default


def _recommendation_entry_stop_target(rec: Mapping[str, Any]) -> tuple[Decimal, Decimal, Decimal, str | None]:
    notes_obj = rec.get("notes")
    notes = notes_obj if isinstance(notes_obj, Mapping) else {}
    source_obj = notes.get("source_signal")
    source_signal = source_obj if isinstance(source_obj, Mapping) else {}
    entry = _decimal_from_money(source_signal.get("close"))
    stop = _decimal_from_money(source_signal.get("invalidation")) or _decimal_from_money(source_signal.get("prior_5d_high"))
    target_r = _as_decimal(source_signal.get("target_r"), Decimal("1.0"))
    if entry <= 0:
        return entry, stop, Decimal("0"), "missing entry price"
    if stop <= 0:
        return entry, stop, Decimal("0"), "missing stop price"
    risk_per_share = entry - stop
    if risk_per_share <= 0:
        return entry, stop, Decimal("0"), "non-positive stop risk"
    target = entry + risk_per_share * target_r
    return entry, stop, target, None


def log_approved_paper_recommendation_trades(
    conn,
    *,
    signal_dt: date | None = None,
    tickers: Sequence[str] | None = None,
    max_trades: int = 3,
    account_equity_usd: Decimal = Decimal("5000"),
    risk_fraction: Decimal = Decimal("0.05"),
    dry_run: bool = False,
) -> dict:
    """Create Postgres paper_trades from approved deterministic recommendations.

    This is paper-only accounting. It never talks to a broker, places orders,
    cancels orders, or moves money. Idempotency is by recommendation_id.
    """
    params: list[object] = []
    scope_clause = ""
    if signal_dt is not None:
        scope_clause += " AND r.notes->>'signal_dt'=%s"
        params.append(signal_dt.isoformat())
    if tickers is not None:
        scope_clause += " AND r.ticker = ANY(%s)"
        params.append([ticker.upper() for ticker in tickers])
    params.append(max(0, max_trades))
    rows = conn.execute(
        f"""
        SELECT r.id, r.ticker, r.recommendation_type, r.notes, st.name, st.status, st.metadata
        FROM recommendations r
        JOIN strategies st ON st.name = r.notes->>'strategy_name'
        WHERE r.status IN ('paper_candidate','paper_logged')
          AND r.notes->>'paper_only'='true'
          AND r.notes->>'no_live_execution'='true'
          {scope_clause}
        ORDER BY r.created_at, r.id
        LIMIT %s
        """,
        params,
    ).fetchall()
    created = 0
    skipped_existing = 0
    blocked_by_strategy_status = 0
    blocked_incomplete = 0
    serializable: list[dict[str, Any]] = []
    for rec_id, ticker, recommendation_type, notes, strategy_name, strategy_status, strategy_metadata in rows:
        rec = {"id": rec_id, "ticker": ticker, "recommendation_type": recommendation_type, "notes": notes or {}}
        metadata = strategy_metadata if isinstance(strategy_metadata, Mapping) else {}
        if strategy_status != "approved" or metadata.get("approval_scope") != "paper_only_no_live_execution" or metadata.get("paper_recommendation_approval") is not True:
            blocked_by_strategy_status += 1
            continue
        exists = conn.execute("SELECT id FROM paper_trades WHERE recommendation_id=%s LIMIT 1", (str(rec_id),)).fetchone()
        if exists:
            skipped_existing += 1
            serializable.append({"recommendation_id": str(rec_id), "ticker": str(ticker), "status": "existing"})
            continue
        entry, stop, target, block_reason = _recommendation_entry_stop_target(rec)
        if block_reason:
            blocked_incomplete += 1
            serializable.append({"recommendation_id": str(rec_id), "ticker": str(ticker), "status": "blocked", "reason": block_reason})
            continue
        risk_amount = account_equity_usd * risk_fraction
        quantity = risk_amount / (entry - stop)
        signal_dt = rec["notes"].get("signal_dt") if isinstance(rec["notes"], Mapping) else None
        trade_notes = {
            "paper_only": True,
            "no_live_execution": True,
            "broker_order_submitted": False,
            "source_recommendation_id": str(rec_id),
            "strategy_name": strategy_name,
            "risk_fraction": str(risk_fraction),
            "risk_amount_usd": _money(risk_amount),
            "entry_baseline": "eod_close",
            "option_spread_advisory": rec["notes"].get("option_spread") if isinstance(rec["notes"], Mapping) else None,
            "equity_fallback": True,
        }
        if not dry_run:
            conn.execute(
                """
                INSERT INTO paper_trades(recommendation_id, ticker, entry_date, entry_price, quantity, instrument, stop_price, target_price, status, data_source, notes)
                VALUES (%s,%s,%s,%s,%s,'equity_fallback_plus_option_spread_advisory',%s,%s,'open','approved_deterministic_recommendation',%s::jsonb)
                """,
                (str(rec_id), str(ticker), signal_dt, float(entry), float(quantity), float(stop), float(target), _json(trade_notes)),
            )
            conn.execute("UPDATE recommendations SET status='paper_logged' WHERE id=%s", (rec_id,))
        created += 1
        serializable.append(
            {
                "recommendation_id": str(rec_id),
                "ticker": str(ticker),
                "entry": _money(entry),
                "stop": _money(stop),
                "target": _money(target),
                "quantity": str(quantity.quantize(Decimal("0.0001"))),
                "status": "open",
            }
        )
    return {
        "dry_run": dry_run,
        "paper_trades_created": created if not dry_run else 0,
        "paper_trades_ranked": len(rows),
        "skipped_existing": skipped_existing,
        "blocked_by_strategy_status": blocked_by_strategy_status,
        "blocked_incomplete": blocked_incomplete,
        "paper_trades": serializable,
        "broker_orders_created": 0,
    }


def propose_approved_setups(
    conn,
    *,
    signal_dt: date,
    for_session: date,
    tickers: Sequence[str] | None = None,
    max_setups: int = 10,
    dry_run: bool = False,
    screening_context: Mapping[str, Any] | None = None,
) -> dict:
    ensure_signal_schema(conn)
    context: dict[str, Any] = dict(screening_context or {})
    context["conn"] = conn
    config = _config_values(conn)
    params: list[object] = [signal_dt]
    ticker_clause = ""
    if tickers is not None:
        ticker_clause = "AND s.ticker = ANY(%s)"
        params.append([t.upper() for t in tickers])
    rows = conn.execute(
        f"""
        SELECT s.ticker, s.direction, s.raw, st.id, st.name, st.status, p.close, f.atr, f.liquidity, f.dollar_vol
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
    blocked_by_strategy_status = 0
    ranked_setups: list[dict[str, Any]] = []
    blocked_setups: list[dict[str, Any]] = []
    current_open_positions, current_heat, _risk_by_ticker = _open_position_risk(conn)
    for ticker, direction, raw, strategy_id, strategy_name, status, close, atr, liquidity, dollar_vol in rows:
        if status != "approved":
            blocked_by_strategy_status += 1
            continue
        setup, reasons = _build_screened_setup(
            ticker=ticker,
            direction=direction,
            raw=raw,
            strategy_id=int(strategy_id),
            strategy_name=str(strategy_name),
            close=close,
            atr=atr,
            liquidity=liquidity,
            dollar_vol=dollar_vol,
            config=config,
            screening_context=context,
            signal_dt=signal_dt,
            for_session=for_session,
            current_open_positions=current_open_positions,
            current_heat=current_heat,
        )
        if reasons:
            blocked_setups.append({"ticker": ticker, "strategy_name": strategy_name, "reasons": reasons})
            continue
        ranked_setups.append(setup)
        current_open_positions += 1
        current_heat += Decimal(setup["size"]["risk_amount_usd"])
    ranked_setups.sort(key=lambda item: (item["score"], item["ticker"]), reverse=True)
    ranked_setups = ranked_setups[: max(0, max_setups)]

    if not dry_run:
        for rank, setup in enumerate(ranked_setups, start=1):
            conn.execute(
                """
                INSERT INTO setups(created_dt, for_session, ticker, strategy_id, direction, liquidity_ok, event_flag, option_structure, iv_view, size, invalidation, thesis, falsification, confidence, rank, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,'pending_review')
                """,
                (
                    signal_dt,
                    for_session,
                    setup["ticker"],
                    setup["strategy_id"],
                    setup["direction"],
                    setup["liquidity_ok"],
                    setup["event_flag"],
                    _json(setup["option_structure"]),
                    _json(setup["iv_view"]),
                    _json(setup["size"]),
                    Decimal(setup["invalidation"]),
                    setup["thesis"],
                    setup["falsification"],
                    setup["confidence"],
                    rank,
                ),
            )
            created += 1

    serializable_ranked = [
        {k: (str(v) if isinstance(v, Decimal) else v) for k, v in setup.items() if k != "score"}
        for setup in ranked_setups
    ]
    return {
        "signal_dt": signal_dt.isoformat(),
        "for_session": for_session.isoformat(),
        "dry_run": dry_run,
        "setups_created": created,
        "setups_ranked": len(ranked_setups),
        "quiet_night": len(ranked_setups) == 0,
        "blocked_by_strategy_status": blocked_by_strategy_status,
        "blocked_setups": blocked_setups,
        "ranked_setups": serializable_ranked,
    }


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
