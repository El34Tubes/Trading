#!/usr/bin/env python3
"""Deterministic Hermes-EOD strategy seeding, signal generation, and approved gate.

This module is deliberately mechanical. It writes research/candidate/approved
strategy signals from price, feature, and earnings rows; it creates actionable
setup tickets only when the originating strategy is already human-approved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence

BROKER_PRICE_DRIFT_WARNING_FRACTION = Decimal("0.05")
BROKER_WIDE_SPREAD_WARNING_FRACTION = Decimal("0.02")

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
    (
        "liquid_rs_breakout_options_volatility_v1",
        "rs_breakout_options_volatility",
        {
            "source": "Wolfy free technical/options-volatility extension 2026-08-12",
            "parent_strategy": "liquid_rs_breakout_close_confirm_1r",
            "requires_backtest": True,
            "breakout_lookback_days": 5,
            "rs_benchmark": "SPY",
            "rs_window_days": 20,
            "min_vol_ratio": "1.2",
            "min_rs_excess_20d": "0.02",
            "max_prior_low_risk_pct": "0.05",
            "market_regime": "SPY_above_50_sma",
            "requires_options_volatility_setup": True,
            "requires_breadth_pct_above_50dma": "0.50",
            "requires_sector_confirmation": True,
            "high_realized_volatility_allowed": True,
            "max_realized_volatility": None,
            "vix_role": "context_not_hard_cap",
            "instrument_policy": "defined_risk_options_only",
            "stop_rule": "close_below_breakout_level",
            "target_r": "1.0",
            "max_hold_days": 10,
            "option_liquidity_hard_gate": True,
            "experimental_forward_recommendations_allowed": True,
            "historical_approval_required_for_experimental_paper": False,
            "allowed_option_structures_v1": ["long_call", "call_debit_spread"],
            "option_dte_min": 7,
            "option_dte_max": 35,
        },
        "New research_only options strategy: volatility contraction then expansion, breadth and sector confirmation; high realized volatility is allowed and no live execution is authorized.",
    ),
    (
        "liquid_rs_breakout_aggressive_options_v2",
        "rs_breakout_aggressive_options",
        {
            "source": "Wolfy aggressive options-only experimental paper profile v2 2026-09-12",
            "parent_strategy": "liquid_rs_breakout_options_volatility_v1",
            "requires_backtest": True,
            "strategy_validated": False,
            "breakout_lookback_days": 5,
            "rs_benchmark": "SPY",
            "rs_window_days": 20,
            "min_vol_ratio": "0.80",
            "min_rs_excess_20d": "-0.03",
            "requires_positive_ticker_return_20d": True,
            "max_prior_low_risk_pct": "0.10",
            "market_regime": "SPY_context_only_not_hard_gate",
            "requires_options_volatility_setup": True,
            "requires_breadth_pct_above_50dma": "0.35",
            "sector_confirmation_role": "context_only_not_required",
            "high_realized_volatility_allowed": True,
            "max_realized_volatility": None,
            "vix_role": "context_not_hard_cap",
            "instrument_policy": "defined_risk_options_only",
            "equity_fallback": False,
            "stop_rule": "close_below_breakout_level",
            "target_r": "1.25",
            "max_hold_days": 7,
            "option_liquidity_hard_gate": True,
            "experimental_forward_recommendations_allowed": True,
            "historical_approval_required_for_experimental_paper": False,
            "allowed_option_structures_v2": ["long_call", "call_debit_spread"],
            "option_dte_min": 7,
            "option_dte_max": 28,
            "selector_policy_version": "aggressive_options_v2",
            "paper_only": True,
            "no_live_execution": True,
        },
        "Separate research_only aggressive options paper profile with lighter underlying gates, exact defined-risk structures, no equity fallback, and no live execution.",
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


def recommendation_universe_tickers(
    conn,
    *,
    signal_dt: date,
    min_history_bars: int = 20,
    explicit_tickers: Sequence[str] | None = None,
) -> list[str]:
    """Return members of the latest immutable pivot-policy snapshot.

    ``min_history_bars`` remains in the compatibility signature, but the
    snapshot builder always enforces the canonical exact 20-session policy.
    Explicit replay tickers are accepted only when every ticker is a member of
    that same snapshot.
    """
    del min_history_bars
    from orchestration_config import MID_SMALL_PIVOT_POLICY

    rows = conn.execute(
        """
        SELECT m.ticker
        FROM recommendation_universe_snapshots s
        JOIN recommendation_universe_members m ON m.snapshot_id=s.snapshot_id
        WHERE s.snapshot_id = (
          SELECT snapshot_id
          FROM recommendation_universe_snapshots
          WHERE signal_dt=%s AND policy_version=%s
          ORDER BY decision_at DESC, source_fingerprint DESC
          LIMIT 1
        )
          AND m.included
        ORDER BY m.ticker
        """,
        (signal_dt, MID_SMALL_PIVOT_POLICY.version),
    ).fetchall()
    included = [str(row[0]).upper() for row in rows]
    if explicit_tickers is None:
        return included
    requested = sorted({str(ticker).strip().upper() for ticker in explicit_tickers if str(ticker).strip()})
    rejected = sorted(set(requested) - set(included))
    if rejected:
        raise ValueError(f"explicit ticker replay failed universe policy: {','.join(rejected)}")
    return requested


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
    require_options_volatility_setup: bool = False,
    require_ticker_outperform_spy: bool = True,
    require_positive_ticker_return: bool = False,
    options_min_breadth: Decimal = Decimal("0.50"),
    require_sector_confirmation: bool = True,
    max_hold_days: int = 10,
    signal_metadata: Mapping[str, Any] | None = None,
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
        atr_dec = Decimal(str(atr))
        finite_values = [close_dec, high_dec, prior_high_dec, prior_low_dec, vol_ratio_dec, atr_dec]
        finite_values.extend(Decimal(str(value)) for value in (sma_fast, sma_slow) if value is not None)
        if not all(value.is_finite() for value in finite_values):
            continue
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
        if require_positive_ticker_return and ticker_return <= 0:
            continue
        if require_ticker_outperform_spy and ticker_return <= spy_return:
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

        approved_adapter_result = None
        if strategy_name == "liquid_rs_breakout_close_confirm_1r":
            from orchestration_config import MID_SMALL_PIVOT_POLICY
            from setup_evaluators import ApprovedBreakoutFacts, evaluate_approved_breakout

            member = conn.execute(
                """SELECT m.sector, m.facts_hash, m.snapshot_id
                     FROM recommendation_universe_members AS m
                     JOIN recommendation_universe_snapshots AS s ON s.snapshot_id=m.snapshot_id
                    WHERE m.ticker=%s AND m.included AND s.signal_dt=%s
                      AND s.policy_version=%s
                    ORDER BY s.decision_at DESC, s.source_fingerprint DESC
                    LIMIT 1""",
                (ticker, signal_dt, MID_SMALL_PIVOT_POLICY.version),
            ).fetchone()
            if member is not None:
                sector, member_facts_hash, snapshot_id = member
                approved_adapter_result = evaluate_approved_breakout(
                    ApprovedBreakoutFacts(
                        ticker=ticker,
                        sector=str(sector),
                        evaluated_at=datetime.combine(signal_dt, datetime.max.time(), tzinfo=timezone.utc),
                        universe_eligible=True,
                        close=close_dec,
                        high=high_dec,
                        prior_five_high=prior_high_dec,
                        prior_five_low=prior_low_dec,
                        sma_fast=sma_fast,
                        sma_slow=sma_slow,
                        volume_ratio=vol_ratio_dec,
                        atr=atr_dec,
                        ticker_return_20d=ticker_return,
                        spy_return_20d=spy_return,
                        spy_close=spy_row[0],
                        spy_sma_50=spy_sma,
                        source_fingerprint=str(member_facts_hash),
                        provenance={"universe_snapshot_id": str(snapshot_id)},
                        benchmark_context={"IWM": {"role": "context_only"}, "MDY": {"role": "context_only"}},
                    )
                )
                if not approved_adapter_result.evaluation.passed:
                    continue

        options_volatility_facts: dict[str, Any] | None = None
        if require_options_volatility_setup:
            feature_row = conn.execute(
                """
                SELECT options_volatility_setup, realized_vol_annualized,
                       pre_breakout_contraction_ratio, range_expansion_ratio,
                       close_location_value, volume_percentile
                FROM options_technical_features WHERE ticker=%s AND dt=%s
                """,
                (ticker, signal_dt),
            ).fetchone()
            breadth_row = conn.execute(
                "SELECT pct_above_50dma, advance_decline_ratio FROM market_breadth WHERE dt=%s",
                (signal_dt,),
            ).fetchone()
            sector_row = conn.execute("SELECT sector FROM universe_symbols WHERE symbol=%s", (ticker,)).fetchone()
            sector = str(sector_row[0]) if sector_row and sector_row[0] else None
            from free_technical_data import SECTOR_ETFS, compute_sector_relative_strength

            sector_etf = SECTOR_ETFS.get(sector or "")
            sector_return = None
            if sector_etf:
                sector_prices = conn.execute(
                    """
                    SELECT cur.close, prev.close
                    FROM prices cur
                    JOIN LATERAL (
                      SELECT close FROM prices WHERE ticker=cur.ticker AND dt <= %s ORDER BY dt DESC LIMIT 1
                    ) prev ON true
                    WHERE cur.ticker=%s AND cur.dt=%s
                    """,
                    (signal_dt - timedelta(days=rs_window_days), sector_etf, signal_dt),
                ).fetchone()
                if sector_prices and sector_prices[1] not in (None, 0):
                    sector_return = Decimal(str(sector_prices[0])) / Decimal(str(sector_prices[1])) - Decimal("1")
            sector_strength = compute_sector_relative_strength(
                ticker=ticker, sector=sector, stock_return=ticker_return,
                sector_return=sector_return, spy_return=spy_return,
            )
            latest_vix = conn.execute(
                """
                SELECT value FROM technical_market_series
                WHERE series='VIX' AND observation_date <= %s
                  AND available_at <= (%s::date + interval '1 day')
                ORDER BY observation_date DESC LIMIT 1
                """,
                (signal_dt, signal_dt),
            ).fetchone()
            feature = dict(zip(
                ("options_volatility_setup", "realized_vol_annualized", "pre_breakout_contraction_ratio", "range_expansion_ratio", "close_location_value", "volume_percentile"),
                feature_row,
            )) if feature_row else None
            breadth = dict(zip(("pct_above_50dma", "advance_decline_ratio"), breadth_row)) if breadth_row else None
            accepted, options_volatility_facts = _options_volatility_gate(
                options_feature=feature,
                breadth=breadth,
                sector_strength=sector_strength,
                market_regime={"vix": latest_vix[0] if latest_vix else None},
                min_breadth_pct_above_50dma=options_min_breadth,
                require_sector_confirmation=require_sector_confirmation,
            )
            if not accepted:
                continue

        raw = {
            "strategy": strategy_name,
            "close": close_dec,
            "prior_5d_high": prior_high_dec,
            "prior_5d_low": prior_low_dec,
            "sma_fast": sma_fast,
            "sma_slow": sma_slow,
            "atr": atr_dec,
            "atr_pct": atr_dec / close_dec if close_dec else None,
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
            "spy_above_sma_required": require_spy_above_sma_days is not None,
            "requires_ticker_outperform_spy": require_ticker_outperform_spy,
            "requires_positive_ticker_return_20d": require_positive_ticker_return,
            "near_high_pct": near_high_pct,
            "breakout_lookback_days": breakout_lookback_days,
            "rs_window_days": rs_window_days,
            "within_5pct_recent_high": within_5pct_recent_high,
            "stop_rule": stop_rule,
            "invalidation": prior_low_dec if stop_rule == "prior_5_day_low" else prior_high_dec,
            "max_hold_days": max_hold_days,
            "target_r": target_r,
            "profit_plan": f"take_partial_or_review_at_{target_r}R_then_trail_remainder",
            "preferred_instrument": "2-3wk slightly OTM call spread",
            "option_liquidity_hard_gate": False,
            "option_liquidity_note": "user_to_evaluate_manually",
            "gap_no_chase_atr": Decimal("0.5"),
            "gate_status": status,
            "reason": "20d RS leader breaking prior 5d high on confirmed volume near highs",
        }
        if options_volatility_facts is not None:
            raw["options_volatility"] = options_volatility_facts
            raw["instrument_policy"] = "defined_risk_options_only"
            raw["option_liquidity_hard_gate"] = True
        if signal_metadata:
            raw.update(signal_metadata)
        if approved_adapter_result is not None:
            evaluation = approved_adapter_result.evaluation
            raw["common_setup_evaluation"] = {
                "facts_hash": approved_adapter_result.facts_hash,
                "gate_facts": evaluation.gate_facts,
                "reason_codes": evaluation.reason_codes,
                "strategy_version": evaluation.strategy_version,
            }
            raw["common_setup_candidate_terms"] = {
                "entry": approved_adapter_result.entry,
                "stop": approved_adapter_result.stop,
                "target": approved_adapter_result.target,
                "score_components": evaluation.score_components,
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
        universe_source = "immutable_mid_small_snapshot"
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
        "liquid_rs_breakout_options_volatility_v1": _generate_liquid_rs_breakout(
            conn,
            tickers=tickers,
            signal_dt=signal_dt,
            strategies=strategies,
            strategy_name="liquid_rs_breakout_options_volatility_v1",
            min_vol_ratio=Decimal("1.2"),
            min_rs_excess=Decimal("0.02"),
            max_stop_risk_pct=Decimal("0.05"),
            require_spy_above_sma_days=50,
            stop_rule="close_below_breakout_level",
            target_r=Decimal("1.0"),
            require_options_volatility_setup=True,
        ),
        "liquid_rs_breakout_aggressive_options_v2": _generate_liquid_rs_breakout(
            conn,
            tickers=tickers,
            signal_dt=signal_dt,
            strategies=strategies,
            strategy_name="liquid_rs_breakout_aggressive_options_v2",
            min_vol_ratio=Decimal("0.80"),
            min_rs_excess=Decimal("-0.03"),
            max_stop_risk_pct=Decimal("0.10"),
            stop_rule="close_below_breakout_level",
            target_r=Decimal("1.25"),
            require_options_volatility_setup=True,
            require_ticker_outperform_spy=False,
            require_positive_ticker_return=True,
            options_min_breadth=Decimal("0.35"),
            require_sector_confirmation=False,
            max_hold_days=7,
            signal_metadata={
                "instrument_policy": "defined_risk_options_only",
                "equity_fallback": False,
                "experimental_forward_test": True,
                "experimental_forward_recommendations_allowed": True,
                "strategy_validated": False,
                "paper_only": True,
                "no_live_execution": True,
                "allowed_option_structures": ["long_call", "call_debit_spread"],
                "option_dte_min": 7,
                "option_dte_max": 28,
                "selector_policy_version": "aggressive_options_v2",
            },
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


def _options_volatility_gate(
    *,
    options_feature: Mapping[str, Any] | None,
    breadth: Mapping[str, Any] | None,
    sector_strength: Mapping[str, Any] | None,
    market_regime: Mapping[str, Any] | None,
    min_breadth_pct_above_50dma: Decimal = Decimal("0.50"),
    require_sector_confirmation: bool = True,
) -> tuple[bool, dict[str, Any]]:
    """Gate the research strategy on setup shape, breadth, and sector context.

    Realized volatility and VIX are preserved as context and deliberately have
    no maximum cap. Defined-risk option liquidity is enforced downstream before
    any recommendation can become an options paper setup. Defaults exactly
    preserve the strict v1 breadth and sector requirements.
    """
    options_feature = options_feature or {}
    breadth = breadth or {}
    sector_strength = sector_strength or {}
    market_regime = market_regime or {}
    pct_above_50 = _as_decimal(breadth.get("pct_above_50dma"), Decimal("0"))
    sector_ok = (
        sector_strength.get("sector_confirmation") is True
        if require_sector_confirmation
        else True
    )
    accepted = bool(
        options_feature.get("options_volatility_setup") is True
        and breadth.get("pct_above_50dma") is not None
        and pct_above_50 >= min_breadth_pct_above_50dma
        and sector_ok
    )
    facts = {
        **dict(options_feature),
        "breadth_pct_above_50dma": pct_above_50,
        "breadth_min_pct_above_50dma": min_breadth_pct_above_50dma,
        "sector_strength": dict(sector_strength),
        "sector_confirmation_required": require_sector_confirmation,
        "sector_context_available": bool(
            sector_strength.get("sector")
            and sector_strength.get("sector_etf")
            and sector_strength.get("stock_vs_sector") is not None
            and sector_strength.get("sector_vs_spy") is not None
        ),
        "market_regime": dict(market_regime),
        "high_realized_volatility_allowed": True,
        "max_realized_volatility": None,
        "vix_is_context_not_hard_cap": True,
        "defined_risk_options_only": True,
    }
    return accepted, facts


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
    options_only = str(_raw_value(raw, "instrument_policy", "")) == "defined_risk_options_only"
    if options_only and instrument_type not in {"option", "options", "call", "put"}:
        reasons.append("options-only strategy requires an option instrument")
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


def _broker_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default
    try:
        return Decimal(str(value).replace("$", "").replace(",", "").strip())
    except Exception:
        return default


def _broker_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _broker_notes_for_ticker(
    ticker: str,
    *,
    entry: Decimal,
    broker_enrichment: Mapping[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[str], bool]:
    """Normalize Robinhood read-only enrichment into recommendation note fields.

    This function is deliberately passive: it records broker-side tradability,
    quote/spread, exposure, earnings, fundamentals, and option-spread metadata;
    it never calls broker order tools and never authorizes live execution.
    """
    if not broker_enrichment:
        return None, [], True
    raw_obj = broker_enrichment.get(ticker.upper()) or broker_enrichment.get(ticker)
    if not isinstance(raw_obj, Mapping):
        return None, [], True

    raw = dict(raw_obj)
    tradability_obj = raw.get("tradability")
    quote_obj = raw.get("quote")
    price_book_obj = raw.get("price_book")
    account_exposure_obj = raw.get("account_exposure")
    earnings_obj = raw.get("earnings")
    option_spread_obj = raw.get("option_spread")
    tradability: Mapping[str, Any] = tradability_obj if isinstance(tradability_obj, Mapping) else {}
    quote: Mapping[str, Any] = quote_obj if isinstance(quote_obj, Mapping) else {}
    price_book: Mapping[str, Any] = price_book_obj if isinstance(price_book_obj, Mapping) else {}
    account_exposure: Mapping[str, Any] = account_exposure_obj if isinstance(account_exposure_obj, Mapping) else {}
    earnings: Mapping[str, Any] = earnings_obj if isinstance(earnings_obj, Mapping) else {}
    option_spread: Mapping[str, Any] = option_spread_obj if isinstance(option_spread_obj, Mapping) else {}

    tradable = _broker_bool(tradability.get("tradable"), default=True)
    halted = _broker_bool(tradability.get("halted"), default=False)
    current_price = _broker_decimal(quote.get("last_price") or quote.get("mark_price") or quote.get("price"), Decimal("0"))
    bid = _broker_decimal(price_book.get("bid_price") or quote.get("bid_price"), Decimal("0"))
    ask = _broker_decimal(price_book.get("ask_price") or quote.get("ask_price"), Decimal("0"))
    spread_pct = Decimal("0")
    if bid > 0 and ask > 0:
        mid = (bid + ask) / Decimal("2")
        if mid > 0:
            spread_pct = (ask - bid) / mid
    price_drift_pct = Decimal("0")
    if entry > 0 and current_price > 0:
        price_drift_pct = abs(current_price - entry) / entry

    option_spread_available = _broker_bool(option_spread.get("available"), default=False)
    existing_equity_position = _broker_bool(account_exposure.get("existing_equity_position"), default=False)
    existing_option_position = _broker_bool(account_exposure.get("existing_option_position"), default=False)
    open_order_warning = _broker_bool(account_exposure.get("open_order_warning"), default=False)
    earnings_window = _broker_bool(earnings.get("within_hold_window"), default=False)

    warnings: list[str] = []
    tradability_block = (not tradable) or halted
    if tradability_block:
        warnings.append("halted_or_not_tradable")
    if price_drift_pct > BROKER_PRICE_DRIFT_WARNING_FRACTION:
        warnings.append(f"price_drift_{price_drift_pct:.2%}_from_eod_baseline")
    if spread_pct > BROKER_WIDE_SPREAD_WARNING_FRACTION:
        warnings.append(f"wide_bid_ask_spread_{spread_pct:.2%}")
    if existing_equity_position:
        warnings.append("existing_equity_position")
    if existing_option_position:
        warnings.append("existing_option_position")
    if open_order_warning:
        warnings.append("open_order_warning")
    if earnings_window:
        warnings.append("earnings_within_expected_hold_window")

    normalized = {
        "source": str(raw.get("source") or "robinhood_mcp"),
        "read_only": True,
        "tradability_block": tradability_block,
        "tradable": tradable,
        "halted": halted,
        "current_price": _money(current_price) if current_price > 0 else None,
        "bid": _money(bid) if bid > 0 else None,
        "ask": _money(ask) if ask > 0 else None,
        "spread_pct": str(spread_pct) if spread_pct > 0 else None,
        "price_drift_pct": str(price_drift_pct) if price_drift_pct > 0 else None,
        "existing_equity_position": existing_equity_position,
        "existing_option_position": existing_option_position,
        "open_order_warning": open_order_warning,
        "earnings_within_hold_window": earnings_window,
        "option_spread_available": option_spread_available,
        "option_spread": option_spread or None,
        "fundamentals": raw.get("fundamentals") if isinstance(raw.get("fundamentals"), Mapping) else None,
        "raw": raw,
    }
    equity_fallback = not option_spread_available
    return normalized, warnings, equity_fallback


def _recomputed_aggressive_v2_option_selection(
    evaluation: Mapping[str, Any], selected: Mapping[str, Any], *, ticker: str,
    underlying_price: Decimal, technical_target: Decimal, signal_dt: date,
) -> dict[str, Any] | None:
    """Fail closed unless canonical v2 recomputation exactly matches the submission."""
    from options_structure_selector import aggressive_options_v2_policy, select_bullish_option_structure

    policy = evaluation.get("policy")
    contracts = evaluation.get("input_contracts")
    if (
        evaluation.get("status") != "selected"
        or evaluation.get("paper_only") is not True
        or evaluation.get("no_live_execution") is not True
        or evaluation.get("broker_order_submitted") is not False
        or not isinstance(policy, Mapping)
        or policy.get("policy_version") != "aggressive_options_v2"
        or not isinstance(contracts, list)
        or not contracts
        or not all(isinstance(contract, Mapping) for contract in contracts)
    ):
        return None
    try:
        decision_time = datetime.fromisoformat(str(policy.get("decision_time")).replace("Z", "+00:00"))
        recomputed = select_bullish_option_structure(
            ticker=ticker,
            underlying_price=underlying_price,
            technical_target=technical_target,
            as_of=signal_dt,
            contracts=contracts,
            policy=aggressive_options_v2_policy(decision_time=decision_time),
        )
    except (TypeError, ValueError, ArithmeticError):
        return None
    canonical = recomputed.get("selected")
    if not isinstance(canonical, Mapping):
        return None
    submitted_json = json.dumps(dict(selected), sort_keys=True, default=str, separators=(",", ":"))
    canonical_json = json.dumps(dict(canonical), sort_keys=True, default=str, separators=(",", ":"))
    return dict(canonical) if submitted_json == canonical_json else None


def _authorized_aggressive_v2_signal(raw: Mapping[str, Any], params: Mapping[str, Any]) -> bool:
    return bool(
        params.get("experimental_forward_recommendations_allowed") is True
        and params.get("strategy_validated") is False
        and params.get("instrument_policy") == "defined_risk_options_only"
        and params.get("equity_fallback") is False
        and params.get("selector_policy_version") == "aggressive_options_v2"
        and raw.get("experimental_forward_recommendations_allowed") is True
        and raw.get("strategy_validated") is False
        and raw.get("instrument_policy") == "defined_risk_options_only"
        and raw.get("equity_fallback") is False
        and raw.get("paper_only") is True
        and raw.get("no_live_execution") is True
        and raw.get("selector_policy_version") == "aggressive_options_v2"
    )


def _durable_option_selection(
    conn,
    evaluation: Mapping[str, Any],
    *,
    ticker: str,
    strategy_name: str,
    signal_dt: date,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Reload and recompute an option decision from its immutable chain snapshot."""
    evaluation_id = evaluation.get("evaluation_id")
    snapshot_id = evaluation.get("snapshot_id")
    if type(evaluation_id) is not int or not isinstance(snapshot_id, str) or not snapshot_id:
        return None
    row = conn.execute(
        """SELECT e.ticker,e.signal_dt,e.strategy_name,e.underlying_price,
                  e.technical_target,e.decision_at,e.evaluation,e.snapshot_id,
                  s.ticker,s.available_at,s.payload_sha256,s.chain
           FROM option_structure_evaluations e
           JOIN option_chain_snapshots s ON s.snapshot_id=e.snapshot_id
           WHERE e.id=%s""",
        (evaluation_id,),
    ).fetchone()
    if row is None:
        return None
    (stored_ticker, stored_dt, stored_strategy, underlying_price, technical_target,
     decision_at, stored_evaluation, stored_snapshot_id, snapshot_ticker,
     available_at, payload_sha256, chain) = row
    stored_payload_hash = hashlib.sha256(
        json.dumps(chain, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if (
        str(stored_ticker).upper() != ticker.upper()
        or stored_dt != signal_dt
        or stored_strategy != strategy_name
        or stored_snapshot_id != snapshot_id
        or str(snapshot_ticker).upper() != ticker.upper()
        or available_at > decision_at
        or stored_payload_hash != payload_sha256
        or evaluation.get("ticker") != ticker.upper()
        or evaluation.get("strategy_name") != strategy_name
        or evaluation.get("payload_sha256") != payload_sha256
    ):
        return None
    from options_structure_selector import (
        SelectorPolicy,
        aggressive_options_v2_policy,
        select_bullish_option_structure,
    )

    policy_data = stored_evaluation.get("policy") if isinstance(stored_evaluation, Mapping) else None
    try:
        policy = (
            aggressive_options_v2_policy(decision_time=decision_at)
            if isinstance(policy_data, Mapping)
            and policy_data.get("policy_version") == "aggressive_options_v2"
            else SelectorPolicy()
        )
        recomputed = select_bullish_option_structure(
            ticker=ticker,
            underlying_price=Decimal(str(underlying_price)),
            technical_target=Decimal(str(technical_target)),
            as_of=signal_dt,
            contracts=chain,
            policy=policy,
        )
    except (TypeError, ValueError, ArithmeticError):
        return None
    canonical = recomputed.get("selected")
    stored_selected = stored_evaluation.get("selected") if isinstance(stored_evaluation, Mapping) else None
    submitted_selected = evaluation.get("selected")
    if not all(isinstance(item, Mapping) for item in (canonical, stored_selected, submitted_selected)):
        return None
    serialized = {
        json.dumps(dict(item), sort_keys=True, default=str, separators=(",", ":"))
        for item in (canonical, stored_selected, submitted_selected)
    }
    if len(serialized) != 1:
        return None
    return dict(canonical), {
        "option_evaluation_id": evaluation_id,
        "option_chain_snapshot_id": snapshot_id,
        "option_chain_payload_sha256": payload_sha256,
        "option_decision_at": decision_at.isoformat(),
    }


def write_experimental_options_recommendations(
    conn,
    *,
    signal_dt: date,
    option_evaluations: Mapping[str, Any],
    max_recommendations: int = 3,
    account_equity_usd: Decimal = Decimal("5000"),
    risk_fraction: Decimal = Decimal("0.05"),
    dry_run: bool = False,
    strategy_name: str = "liquid_rs_breakout_options_volatility_v1",
) -> dict:
    """Write unvalidated, paper-only option expressions for qualifying signals.

    Historical approval is intentionally not required for this named research
    strategy. A selected, defined-risk, exact option structure remains mandatory.
    """
    ensure_signal_schema(conn)
    from recommendation_writer import RecommendationCandidate, write_ranked_recommendations

    aggressive_v2 = strategy_name == "liquid_rs_breakout_aggressive_options_v2"
    effective_max_recommendations = max_recommendations
    effective_risk_fraction = min(risk_fraction, Decimal("0.05"))
    risk_budget = account_equity_usd * effective_risk_fraction
    rows = conn.execute("""
        SELECT s.ticker,s.raw,st.id,st.name,st.status,st.params
        FROM signals s JOIN strategies st ON st.id=s.strategy_id
        WHERE s.dt=%s AND st.name=%s
          AND lower(coalesce(s.direction,'')) IN ('long','buy')
        ORDER BY s.ticker
    """, (signal_dt, strategy_name)).fetchall()
    eligible: list[dict[str, Any]] = []
    blocked = 0
    for ticker, raw, strategy_id, row_strategy_name, strategy_status, strategy_params in rows:
        evaluation = option_evaluations.get(str(ticker).upper()) or option_evaluations.get(str(ticker))
        selected = evaluation.get("selected") if isinstance(evaluation, Mapping) else None
        raw_dict = raw if isinstance(raw, Mapping) else json.loads(raw or "{}")
        params_dict = strategy_params if isinstance(strategy_params, Mapping) else {}
        entry = _as_decimal(_raw_value(raw_dict, "close"), Decimal("0"))
        stop = _as_decimal(_raw_value(raw_dict, "invalidation"), Decimal("0"))
        target_r = _as_decimal(_raw_value(raw_dict, "target_r"), Decimal("1"))
        target = entry + max(entry - stop, Decimal("0")) * target_r
        max_hold_days = params_dict.get("max_hold_days", 10)
        if type(max_hold_days) is not int or not 1 <= max_hold_days <= 60:
            blocked += 1
            continue
        if not isinstance(selected, Mapping) or selected.get("defined_risk") is not True:
            blocked += 1
            continue
        durable = _durable_option_selection(
            conn,
            dict(evaluation),
            ticker=str(ticker),
            strategy_name=str(row_strategy_name),
            signal_dt=signal_dt,
        )
        if durable is None:
            blocked += 1
            continue
        selected, provenance = durable
        if aggressive_v2:
            canonical_selected = (
                _recomputed_aggressive_v2_option_selection(
                    evaluation, selected, ticker=str(ticker), underlying_price=entry,
                    technical_target=target, signal_dt=signal_dt,
                )
                if isinstance(evaluation, Mapping)
                else None
            )
            if (
                strategy_status != "research_only"
                or not _authorized_aggressive_v2_signal(raw_dict, params_dict)
                or canonical_selected is None
            ):
                blocked += 1
                continue
            selected = canonical_selected
        debit = _as_decimal(selected.get("max_loss_per_contract"), Decimal("0"))
        if debit <= 0 or (aggressive_v2 and debit > risk_budget):
            blocked += 1
            continue
        eligible.append({"ticker": str(ticker), "raw": raw_dict, "strategy_id": int(strategy_id), "strategy_name": str(row_strategy_name), "strategy_status": str(strategy_status), "selected": dict(selected), "provenance": provenance, "max_loss": debit, "max_hold_days": max_hold_days, "sector": str(_raw_value(raw_dict, "sector", "Unknown")) or "Unknown"})
    eligible.sort(key=lambda item: (-_recommendation_score(item["raw"]), item["ticker"]))
    skipped = 0
    serializable: list[dict[str, Any]] = []
    items_by_identity = {
        (item["ticker"].upper(), item["strategy_name"]): item for item in eligible
    }

    def insert_candidate(candidate) -> bool:
        nonlocal blocked, skipped
        item = items_by_identity[(candidate.ticker, candidate.strategy_name)]
        ticker, raw, selected = item["ticker"], item["raw"], item["selected"]
        entry = _as_decimal(_raw_value(raw, "close"), Decimal("0"))
        stop = _as_decimal(_raw_value(raw, "invalidation"), Decimal("0"))
        target_r = _as_decimal(_raw_value(raw, "target_r"), Decimal("1"))
        target = entry + max(entry - stop, Decimal("0")) * target_r
        contracts = int(risk_budget // item["max_loss"])
        if contracts < 1:
            blocked += 1
            return False
        notes = {
            "experimental_forward_test": True, "strategy_validated": False,
            "historical_approval_gate_overridden_for_paper_research": True,
            "paper_only": True, "no_live_execution": True, "broker_order_submitted": False,
            "equity_fallback": False, "signal_dt": signal_dt.isoformat(),
            "strategy_id": item["strategy_id"], "strategy_name": item["strategy_name"],
            "strategy_status_at_selection": item["strategy_status"], "sector": item["sector"],
            "source_signal": raw, "option_structure": selected,
            "paper_account_usd": str(account_equity_usd), "risk_fraction": str(effective_risk_fraction),
            "paper_risk_budget_usd": str(risk_budget), "paper_contracts": contracts,
            "max_loss_per_contract_usd": str(item["max_loss"]),
            "total_max_loss_usd": str(item["max_loss"] * contracts),
            "position_sizing_basis": "maximum_defined_option_loss",
            **item["provenance"],
        }
        if aggressive_v2:
            notes.update(
                {
                    "experimental_forward_recommendations_allowed": True,
                    "selector_policy_version": "aggressive_options_v2",
                    "instrument_policy": "defined_risk_options_only",
                }
            )
        inserted = conn.execute("""
            INSERT INTO recommendations(ticker,action,recommendation_type,thesis,setup_type,entry_zone,entry_trigger,stop,target,risk_reward,confidence,position_size_suggestion,holding_period,status,notes)
            VALUES (%s,'buy','experimental_defined_risk_option',%s,%s,%s,%s,%s,%s,%s,'experimental',%s,%s,'paper_candidate',%s::jsonb)
            ON CONFLICT (ticker, (notes->>'signal_dt'), (notes->>'strategy_name'))
              WHERE status IN ('paper_candidate','paper_logged')
                AND notes->>'signal_dt' IS NOT NULL
                AND notes->>'strategy_name' IS NOT NULL
            DO NOTHING
            RETURNING id
        """, (
            ticker, f"Experimental forward test of deterministic {item['strategy_name']}; not historically validated and no live execution.",
            item["strategy_name"], f"Underlying EOD baseline {_money(entry)}",
            f"Paper option expression using exact selected contracts; underlying baseline {_money(entry)}.",
            f"Underlying close below {_money(stop)} invalidates thesis.", f"Underlying technical target {_money(target)}.", f"{target_r}R underlying thesis",
            f"{contracts} paper contract(s), sized from ${item['max_loss']} maximum loss each.", f"Up to {item['max_hold_days']} trading days", _json(notes),
        )).fetchone()
        if inserted is None:
            skipped += 1
            serializable.append({"ticker": ticker, "status": "existing"})
            return False
        serializable.append({"ticker": ticker, "status": "paper_candidate", "structure": selected.get("structure"), "contracts": contracts})
        return True

    candidates = [
        RecommendationCandidate(
            ticker=item["ticker"], strategy_name=item["strategy_name"],
            signal_dt=signal_dt, sector=item["sector"],
            risk_fraction=effective_risk_fraction,
        )
        for item in eligible
    ]
    write_result = write_ranked_recommendations(
        conn, candidates=candidates, insert_candidate=insert_candidate,
        max_to_write=effective_max_recommendations, dry_run=dry_run,
    )
    skipped += sum(1 for _ticker, reason in write_result.blocked if reason in {"duplicate_ticker", "insert_conflict"})
    blocked += sum(1 for _ticker, reason in write_result.blocked if reason not in {"duplicate_ticker", "insert_conflict"})
    if dry_run:
        for candidate in write_result.selected:
            item = items_by_identity[(candidate.ticker, candidate.strategy_name)]
            serializable.append({"ticker": candidate.ticker, "status": "paper_candidate", "structure": item["selected"].get("structure")})
    return {
        "signal_dt": signal_dt.isoformat(), "dry_run": dry_run,
        "recommendations_created": write_result.inserted,
        "recommendations_ranked": len(write_result.selected),
        "skipped_existing": skipped, "blocked_by_option_quality": blocked,
        "broker_orders_created": 0, "recommendations": serializable,
    }


def write_pivot_paper_recommendations(
    conn,
    *,
    recommendations: Sequence[Any],
    signal_dt: date,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Write globally allocated exact instruments to the paper ledger only."""
    from recommendation_writer import write_pivot_instrument_recommendations

    result = write_pivot_instrument_recommendations(
        conn,
        recommendations=recommendations,
        signal_dt=signal_dt,
        dry_run=dry_run,
    )
    return {
        "signal_dt": signal_dt.isoformat(),
        "dry_run": dry_run,
        "recommendations_created": result.inserted,
        "paper_trades_created": result.paper_trades_inserted,
        "recommendations_ranked": len(result.selected),
        "writer_blocked": [
            {"ticker": ticker, "reason": reason} for ticker, reason in result.blocked
        ],
        "paper_only": True,
        "no_live_execution": True,
        "broker_orders_created": result.broker_orders_created,
    }


def write_approved_paper_recommendations(
    conn,
    *,
    signal_dt: date,
    tickers: Sequence[str] | None = None,
    max_recommendations: int = 3,
    risk_fraction: Decimal = Decimal("0.05"),
    dry_run: bool = False,
    broker_enrichment: Mapping[str, Any] | None = None,
) -> dict:
    """Write approved-strategy deterministic paper recommendations to Postgres.

    This is paper-only: no broker execution and no paper_trades insert. The paper
    logging step is a separate gate. Recommendations are sourced only from
    strategies with status='approved'.
    """
    ensure_signal_schema(conn)
    from recommendation_writer import RecommendationCandidate, write_ranked_recommendations

    effective_risk_fraction = min(Decimal(str(risk_fraction)), Decimal("0.05"))
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
                "sector": str(_raw_value(raw_dict, "sector", "Unknown")) or "Unknown",
            }
        )
    approved.sort(key=lambda item: (-item["score"], item["ticker"]))
    skipped_existing = 0
    serializable: list[dict[str, Any]] = []
    items_by_identity = {
        (item["ticker"].upper(), item["strategy_name"]): item for item in approved
    }

    def insert_candidate(candidate) -> bool:
        nonlocal skipped_existing
        item = items_by_identity[(candidate.ticker, candidate.strategy_name)]
        raw = item["raw"]
        ticker = item["ticker"]
        entry = _as_decimal(_raw_value(raw, "close"), Decimal("0"))
        invalidation = _as_decimal(_raw_value(raw, "invalidation"), _as_decimal(_raw_value(raw, "prior_5d_high"), Decimal("0")))
        risk_per_share = max(entry - invalidation, Decimal("0.01"))
        target_r = _as_decimal(_raw_value(raw, "target_r"), Decimal("1.0"))
        target = entry + risk_per_share * target_r
        broker_notes, broker_warnings, equity_fallback = _broker_notes_for_ticker(ticker, entry=entry, broker_enrichment=broker_enrichment)
        notes = {
            "paper_only": True,
            "no_live_execution": True,
            "broker_order_submitted": False,
            "robinhood_read_only": True,
            "broker_warnings": broker_warnings,
            "review_gate_required": False,
            "sentinel_yang_required": False,
            "paper_entry_baseline": "eod_close",
            "signal_dt": signal_dt.isoformat(),
            "strategy_id": item["strategy_id"],
            "strategy_name": item["strategy_name"],
            "sector": item["sector"],
            "risk_fraction": str(effective_risk_fraction),
            "source_signal": {k: (str(v) if isinstance(v, Decimal) else v) for k, v in raw.items()},
            "option_spread": (broker_notes.get("option_spread") if broker_notes and broker_notes.get("option_spread_available") else {
                "structure": _raw_value(raw, "preferred_instrument", "2-3wk slightly OTM call spread"),
                "exact_contract": None,
                "liquidity_hard_gate": False,
                "user_evaluates_liquidity_manually": True,
            }),
            "equity_fallback": equity_fallback,
            "future_same_gate_auto_activation_allowed": True,
        }
        if broker_notes is not None:
            notes["broker_enrichment"] = broker_notes
        payload = {
            "ticker": ticker,
            "strategy_name": item["strategy_name"],
            "entry": _money(entry),
            "stop": _money(invalidation),
            "target": _money(target),
            "risk_fraction": str(effective_risk_fraction),
        }
        inserted = conn.execute(
            """
            INSERT INTO recommendations(ticker, action, recommendation_type, thesis, setup_type, entry_zone, entry_trigger, stop, target, risk_reward, confidence, position_size_suggestion, holding_period, status, notes)
            VALUES (%s,'buy','equity_plus_option_spread_when_data_exists',%s,%s,%s,%s,%s,%s,%s,'medium-high',%s,%s,'paper_candidate',%s::jsonb)
            ON CONFLICT (ticker, (notes->>'signal_dt'), (notes->>'strategy_name'))
              WHERE status IN ('paper_candidate','paper_logged')
                AND notes->>'signal_dt' IS NOT NULL
                AND notes->>'strategy_name' IS NOT NULL
            DO NOTHING
            RETURNING id
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
                f"Paper risk {effective_risk_fraction * Decimal('100'):.2f}% of account; globally capped paper portfolio.",
                "Up to 10 trading days",
                _json(notes),
            ),
        ).fetchone()
        if inserted is None:
            skipped_existing += 1
            serializable.append({**payload, "status": "existing", "broker_enriched": broker_notes is not None})
            return False
        serializable.append({**payload, "status": "paper_candidate", "broker_enriched": broker_notes is not None})
        return True

    candidates = [
        RecommendationCandidate(
            ticker=item["ticker"], strategy_name=item["strategy_name"],
            signal_dt=signal_dt, sector=item["sector"],
            risk_fraction=effective_risk_fraction,
        )
        for item in approved
    ]
    write_result = write_ranked_recommendations(
        conn, candidates=candidates, insert_candidate=insert_candidate,
        max_to_write=max_recommendations, dry_run=dry_run,
    )
    skipped_existing += sum(1 for _ticker, reason in write_result.blocked if reason in {"duplicate_ticker", "insert_conflict"})
    if dry_run:
        for candidate in write_result.selected:
            item = items_by_identity[(candidate.ticker, candidate.strategy_name)]
            raw = item["raw"]
            entry = _as_decimal(_raw_value(raw, "close"), Decimal("0"))
            invalidation = _as_decimal(_raw_value(raw, "invalidation"), _as_decimal(_raw_value(raw, "prior_5d_high"), Decimal("0")))
            target_r = _as_decimal(_raw_value(raw, "target_r"), Decimal("1.0"))
            target = entry + max(entry - invalidation, Decimal("0.01")) * target_r
            serializable.append({
                "ticker": candidate.ticker, "strategy_name": candidate.strategy_name,
                "entry": _money(entry), "stop": _money(invalidation), "target": _money(target),
                "risk_fraction": str(effective_risk_fraction), "status": "paper_candidate",
                "broker_enriched": False,
            })
    return {
        "signal_dt": signal_dt.isoformat(),
        "dry_run": dry_run,
        "recommendations_created": write_result.inserted,
        "recommendations_ranked": len(write_result.selected),
        "skipped_existing": skipped_existing,
        "blocked_by_global_cap": sum(1 for _ticker, reason in write_result.blocked if reason not in {"duplicate_ticker", "insert_conflict"}),
        "blocked_by_strategy_status": blocked_by_strategy_status,
        "paper_trades_created": 0,
        "broker_enriched": sum(1 for rec in serializable if rec.get("broker_enriched")),
        "broker_orders_created": 0,
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
            "equity_fallback": (rec["notes"].get("equity_fallback") if isinstance(rec["notes"], Mapping) else True),
            "broker_enrichment": (rec["notes"].get("broker_enrichment") if isinstance(rec["notes"], Mapping) else None),
            "broker_warnings": (rec["notes"].get("broker_warnings") if isinstance(rec["notes"], Mapping) else []),
            "robinhood_read_only": (rec["notes"].get("robinhood_read_only") if isinstance(rec["notes"], Mapping) else True),
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
