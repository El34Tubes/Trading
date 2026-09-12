from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from eod_price_features import compute_and_store_features, ingest_price_bars
from test_db import test_connection
from test_eod_signals import _breakout_bars, _cleanup


STRATEGY = "liquid_rs_breakout_aggressive_options_v2"
SIGNAL_DT = date(2099, 2, 4)


def _seed_market(conn, ticker: str, *, include_feature: bool = True, include_breadth: bool = True) -> None:
    from eod_signals import seed_default_strategies

    seed_default_strategies(conn)
    _cleanup(conn, [ticker, "SPY"])
    conn.execute("DELETE FROM options_technical_features WHERE ticker=%s", (ticker,))
    conn.execute("DELETE FROM market_breadth WHERE dt=%s", (SIGNAL_DT,))
    # The stock is positive over 20 days but trails SPY by less than 3%.
    ingest_price_bars(
        conn,
        _breakout_bars(ticker, daily_step=Decimal("0.10"), breakout_lift=Decimal("1.60")),
        source="unit-aggressive-options-v2",
    )
    ingest_price_bars(
        conn,
        _breakout_bars("SPY", daily_step=Decimal("0.16"), breakout_lift=Decimal("0.00")),
        source="unit-aggressive-options-v2",
    )
    compute_and_store_features(
        conn,
        tickers=[ticker, "SPY"],
        sma_fast_window=5,
        sma_slow_window=20,
        volume_window=5,
        atr_window=5,
        min_dollar_vol=Decimal("1000"),
    )
    if include_feature:
        conn.execute(
            """INSERT INTO options_technical_features(
                 ticker,dt,realized_vol_annualized,pre_breakout_contraction_ratio,
                 range_expansion_ratio,close_location_value,volume_percentile,
                 options_volatility_setup,high_volatility_allowed,transformation_version)
               VALUES (%s,%s,1.80,0.60,2.10,0.85,0.95,true,true,'unit-v2')""",
            (ticker, SIGNAL_DT),
        )
    if include_breadth:
        conn.execute(
            """INSERT INTO market_breadth(
                 dt,eligible_count,advancers,decliners,advance_decline_ratio,
                 pct_above_50dma,universe_definition,transformation_version)
               VALUES (%s,100,40,60,0.6667,0.35,'unit','unit-v2')""",
            (SIGNAL_DT,),
        )


def _cleanup_market(conn, ticker: str) -> None:
    conn.execute("DELETE FROM options_technical_features WHERE ticker=%s", (ticker,))
    conn.execute("DELETE FROM market_breadth WHERE dt=%s", (SIGNAL_DT,))
    _cleanup(conn, [ticker, "SPY"])


def test_v2_lighter_gate_accepts_positive_laggard_rejected_by_v1_and_audits_policy():
    pytest.importorskip("psycopg")
    from eod_signals import generate_eod_signals

    ticker = "ZZAGGV2"
    with test_connection() as conn:
        try:
            _seed_market(conn, ticker)
            result = generate_eod_signals(conn, tickers=[ticker], signal_dt=SIGNAL_DT)
            rows = conn.execute(
                """SELECT st.name,s.raw FROM signals s JOIN strategies st ON st.id=s.strategy_id
                   WHERE s.ticker=%s AND s.dt=%s AND st.name IN (%s,%s)""",
                (ticker, SIGNAL_DT, "liquid_rs_breakout_options_volatility_v1", STRATEGY),
            ).fetchall()
        finally:
            _cleanup_market(conn, ticker)

    by_name = {name: raw for name, raw in rows}
    assert result["signals_by_strategy"]["liquid_rs_breakout_options_volatility_v1"] == 0
    assert result["signals_by_strategy"][STRATEGY] == 1
    raw = by_name[STRATEGY]
    assert Decimal(str(raw["ticker_return_20d"])) > 0
    assert Decimal("-0.03") <= Decimal(str(raw["rs_excess_20d"])) < Decimal("0.02")
    assert raw["min_rs_excess_20d"] == "-0.03"
    assert raw["min_vol_ratio"] == "0.80"
    assert raw["max_stop_risk_pct"] == "0.10"
    assert raw["spy_above_sma_required"] is False
    assert raw["requires_positive_ticker_return_20d"] is True
    assert raw["instrument_policy"] == "defined_risk_options_only"
    assert raw["equity_fallback"] is False
    assert raw["experimental_forward_test"] is True
    assert raw["experimental_forward_recommendations_allowed"] is True
    assert raw["strategy_validated"] is False
    assert raw["paper_only"] is True
    assert raw["no_live_execution"] is True
    assert raw["max_hold_days"] == 7
    assert raw["target_r"] == "1.25"
    assert raw["allowed_option_structures"] == ["long_call", "call_debit_spread"]
    assert raw["option_dte_min"] == 7
    assert raw["option_dte_max"] == 28
    assert raw["selector_policy_version"] == "aggressive_options_v2"
    assert raw["options_volatility"]["sector_confirmation_required"] is False
    assert raw["options_volatility"]["sector_context_available"] is False


@pytest.mark.parametrize("missing", ["feature", "breadth"])
def test_v2_fails_closed_when_required_forward_context_is_missing(missing: str):
    pytest.importorskip("psycopg")
    from eod_signals import generate_eod_signals

    ticker = f"ZZMISS{missing.upper()}"
    with test_connection() as conn:
        try:
            _seed_market(conn, ticker, include_feature=missing != "feature", include_breadth=missing != "breadth")
            result = generate_eod_signals(conn, tickers=[ticker], signal_dt=SIGNAL_DT)
        finally:
            _cleanup_market(conn, ticker)
    assert result["signals_by_strategy"][STRATEGY] == 0
