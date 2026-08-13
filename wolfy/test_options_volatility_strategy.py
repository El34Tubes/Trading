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
