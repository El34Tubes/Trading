from decimal import Decimal


def test_options_volatility_strategy_is_research_only_and_options_only():
    from eod_signals import DEFAULT_STRATEGIES

    by_name = {row[0]: row for row in DEFAULT_STRATEGIES}
    row = by_name["liquid_rs_breakout_options_volatility_v1"]
    assert row[2]["instrument_policy"] == "defined_risk_options_only"
    assert row[2]["requires_options_volatility_setup"] is True
    assert row[2]["high_realized_volatility_allowed"] is True
    assert row[2]["max_realized_volatility"] is None
    assert "research_only" in row[3]


def test_aggressive_options_v2_metadata_is_explicit_and_does_not_mutate_v1():
    from eod_signals import DEFAULT_STRATEGIES

    by_name = {row[0]: row for row in DEFAULT_STRATEGIES}
    v1 = by_name["liquid_rs_breakout_options_volatility_v1"]
    v2 = by_name["liquid_rs_breakout_aggressive_options_v2"]

    assert v1[2]["min_vol_ratio"] == "1.2"
    assert v1[2]["option_dte_max"] == 35
    assert v2[1] == "rs_breakout_aggressive_options"
    assert v2[2] == {
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
    }
    assert "research_only" in v2[3]
    assert "no live" in v2[3].lower()


def test_options_only_setup_rejects_equity_fallback():
    from datetime import date
    from eod_signals import _build_screened_setup

    class EmptyEventsConn:
        class Result:
            @staticmethod
            def fetchall():
                return []

        def execute(self, *_args, **_kwargs):
            return self.Result()

    setup, reasons = _build_screened_setup(
        ticker="ABC",
        direction="long",
        raw={"instrument_policy": "defined_risk_options_only", "stop_price": "95"},
        strategy_id=1,
        strategy_name="liquid_rs_breakout_options_volatility_v1",
        close=Decimal("100"),
        atr=Decimal("2"),
        liquidity=True,
        dollar_vol=Decimal("100000000"),
        config={"paper_account_usd": "100000", "paper_risk_fraction": "0.05"},
        screening_context={"conn": EmptyEventsConn(), "instrument_context": {"ABC": {"instrument_type": "equity"}}},
        signal_dt=date(2026, 8, 11),
        for_session=date(2026, 8, 12),
        current_open_positions=0,
        current_heat=Decimal("0"),
    )
    assert setup["option_structure"]["instrument_type"] == "equity"
    assert "options-only strategy requires an option instrument" in reasons


def test_options_volatility_gate_accepts_high_volatility_but_requires_structure_and_breadth():
    from eod_signals import _options_volatility_gate

    accepted, facts = _options_volatility_gate(
        options_feature={
            "options_volatility_setup": True,
            "realized_vol_annualized": Decimal("1.25"),
            "pre_breakout_contraction_ratio": Decimal("0.60"),
            "range_expansion_ratio": Decimal("2.1"),
            "close_location_value": Decimal("0.85"),
            "volume_percentile": Decimal("0.95"),
        },
        breadth={"pct_above_50dma": Decimal("0.55"), "advance_decline_ratio": Decimal("1.4")},
        sector_strength={"sector_confirmation": True, "sector_etf": "XLK", "stock_vs_sector": Decimal("0.03"), "sector_vs_spy": Decimal("0.02")},
        market_regime={"vix": Decimal("38"), "vix_percentile_252": Decimal("0.92")},
    )
    assert accepted is True
    assert facts["realized_vol_annualized"] == Decimal("1.25")
    assert facts["high_realized_volatility_allowed"] is True
    assert facts["vix_is_context_not_hard_cap"] is True

    rejected, _ = _options_volatility_gate(
        options_feature={"options_volatility_setup": False, "realized_vol_annualized": Decimal("0.20")},
        breadth={"pct_above_50dma": Decimal("0.70")},
        sector_strength={"sector_confirmation": True},
        market_regime={"vix": Decimal("12")},
    )
    assert rejected is False


def test_aggressive_options_volatility_gate_lowers_breadth_and_records_optional_sector_context():
    from eod_signals import _options_volatility_gate

    accepted, facts = _options_volatility_gate(
        options_feature={"options_volatility_setup": True, "realized_vol_annualized": Decimal("1.80")},
        breadth={"pct_above_50dma": Decimal("0.35")},
        sector_strength=None,
        market_regime={"vix": Decimal("44")},
        min_breadth_pct_above_50dma=Decimal("0.35"),
        require_sector_confirmation=False,
    )

    assert accepted is True
    assert facts["breadth_min_pct_above_50dma"] == Decimal("0.35")
    assert facts["sector_confirmation_required"] is False
    assert facts["sector_strength"] == {}
    assert facts["sector_context_available"] is False

    for feature, breadth in ((None, {"pct_above_50dma": Decimal("0.80")}), ({"options_volatility_setup": True}, None)):
        rejected, _ = _options_volatility_gate(
            options_feature=feature,
            breadth=breadth,
            sector_strength=None,
            market_regime=None,
            min_breadth_pct_above_50dma=Decimal("0.35"),
            require_sector_confirmation=False,
        )
        assert rejected is False
