from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from options_structure_selector import SelectorPolicy, select_bullish_option_structure


def _c(symbol: str, expiration: str, strike: str, bid: str, ask: str, *, oi: int = 500, volume: int = 50, iv: str = "0.40") -> dict:
    return {
        "symbol": symbol,
        "option_type": "call",
        "expiration": expiration,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "open_interest": oi,
        "volume": volume,
        "implied_volatility": iv,
        "quote_at": "2026-08-12T20:00:00+00:00",
        "multiplier": 100,
        "standard_contract": True,
    }


def test_selector_chooses_target_aligned_debit_spread_when_calls_are_expensive():
    chain = [
        _c("XYZ260828C00100000", "2026-08-28", "100", "7.80", "8.20", iv="0.85"),
        _c("XYZ260828C00105000", "2026-08-28", "105", "5.20", "5.50", iv="0.82"),
        _c("XYZ260828C00110000", "2026-08-28", "110", "3.20", "3.45", iv="0.80"),
    ]
    result = select_bullish_option_structure(
        ticker="XYZ", underlying_price=Decimal("100"), technical_target=Decimal("110"),
        as_of=date(2026, 8, 12), contracts=chain,
    )
    assert result["selected"]["structure"] == "call_debit_spread"
    assert result["selected"]["long_leg"]["strike"] == "100"
    assert result["selected"]["short_leg"]["strike"] == "110"
    assert result["selected"]["defined_risk"] is True
    assert result["selected"]["max_loss_per_contract"] == result["selected"]["conservative_debit"] * 100
    assert len(result["evaluated_candidates"]) > 1


def test_selector_can_choose_long_call_when_upside_is_not_capped_by_target():
    chain = [
        _c("ABC260904C00095000", "2026-09-04", "95", "6.00", "6.10", iv="0.25"),
        _c("ABC260904C00100000", "2026-09-04", "100", "2.10", "2.20", iv="0.24"),
        _c("ABC260904C00110000", "2026-09-04", "110", "0.25", "0.30", iv="0.23"),
    ]
    result = select_bullish_option_structure(
        ticker="ABC", underlying_price=Decimal("100"), technical_target=Decimal("118"),
        as_of=date(2026, 8, 12), contracts=chain,
    )
    assert result["selected"]["structure"] == "long_call"
    assert result["selected"]["long_leg"]["strike"] == "100"


def test_selector_rejects_stale_wide_or_illiquid_contracts_instead_of_forcing_trade():
    chain = [
        _c("BAD260821C00100000", "2026-08-21", "100", "1.00", "3.00", oi=2, volume=0),
        {**_c("BAD260821C00105000", "2026-08-21", "105", "0.00", "1.00"), "quote_at": "2026-08-10T20:00:00+00:00"},
    ]
    result = select_bullish_option_structure(
        ticker="BAD", underlying_price=Decimal("100"), technical_target=Decimal("108"),
        as_of=date(2026, 8, 12), contracts=chain,
    )
    assert result["selected"] is None
    assert result["status"] == "no_tradable_option_structure"
    assert result["rejected_contracts"]


def test_selector_deterministically_uses_7_to_35_dte_and_ignores_outside_window():
    chain = [
        _c("DTE260814C00100000", "2026-08-14", "100", "1.00", "1.10"),
        _c("DTE260821C00100000", "2026-08-21", "100", "2.00", "2.10"),
        _c("DTE260828C00110000", "2026-08-28", "110", "0.50", "0.60"),
        _c("DTE261002C00100000", "2026-10-02", "100", "8.00", "8.10"),
    ]
    result = select_bullish_option_structure(
        ticker="DTE", underlying_price=Decimal("100"), technical_target=Decimal("110"),
        as_of=date(2026, 8, 12), contracts=chain,
    )
    assert result["selected"] is not None
    assert 7 <= result["selected"]["dte"] <= 35
    assert any("dte_outside_7_35" in row["reasons"] for row in result["rejected_contracts"])


def test_selector_rejects_future_or_old_quote_timestamps():
    policy = SelectorPolicy(decision_time=datetime(2026, 8, 12, 20, 5, tzinfo=timezone.utc))
    chain = [
        {**_c("TIME260821C00100000", "2026-08-21", "100", "2.00", "2.10"), "quote_at": "2026-08-12T18:00:00+00:00"},
        {**_c("TIME260821C00105000", "2026-08-21", "105", "0.50", "0.60"), "quote_at": "2026-08-12T20:06:00+00:00"},
    ]
    result = select_bullish_option_structure(
        ticker="TIME", underlying_price=Decimal("100"), technical_target=Decimal("108"),
        as_of=date(2026, 8, 12), contracts=chain, policy=policy,
    )
    assert result["selected"] is None
    reasons = {reason for row in result["rejected_contracts"] for reason in row["reasons"]}
    assert "stale_quote" in reasons
    assert "quote_after_decision_time" in reasons


def test_aggressive_policy_selects_economically_positive_modest_otm_long_call():
    from options_structure_selector import aggressive_options_v2_policy

    policy = aggressive_options_v2_policy()
    chain = [
        _c("AGG260821C00103000", "2026-08-21", "103", "0.65", "0.85", oi=10, volume=0),
    ]
    result = select_bullish_option_structure(
        ticker="AGG", underlying_price=Decimal("100"), technical_target=Decimal("108"),
        as_of=date(2026, 8, 12), contracts=chain, policy=policy,
    )

    assert result["selected"]["structure"] == "long_call"
    assert result["selected"]["long_leg"]["strike"] == "103"
    assert result["selected"]["target_profit"] > 0
    assert result["selected"]["conservative_debit"] == Decimal("0.8100")
    assert result["policy"]["policy_version"] == "aggressive_options_v2"
    assert result["policy"]["min_long_moneyness"] == "0.90"
    assert result["policy"]["max_long_moneyness"] == "1.05"
    assert result["policy"]["fill_spread_fraction"] == "0.80"


def test_aggressive_policy_rejects_long_leg_over_five_percent_otm_with_audit_reason():
    from options_structure_selector import aggressive_options_v2_policy

    result = select_bullish_option_structure(
        ticker="LOTTO", underlying_price=Decimal("100"), technical_target=Decimal("112"),
        as_of=date(2026, 8, 12),
        contracts=[_c("LOTTO260821C00105010", "2026-08-21", "105.01", "0.20", "0.25", oi=100, volume=1)],
        policy=aggressive_options_v2_policy(),
    )

    assert result["selected"] is None
    assert result["status"] == "no_tradable_option_structure"
    assert result["rejected_long_legs"] == [
        {"symbol": "LOTTO260821C00105010", "reasons": ["long_moneyness_above_1.05"]}
    ]


def test_aggressive_policy_accepts_thirty_five_percent_relative_spread_boundary():
    from options_structure_selector import aggressive_options_v2_policy

    bid = Decimal("0.65")
    ask = bid * (Decimal("2") + Decimal("0.35")) / (Decimal("2") - Decimal("0.35"))
    result = select_bullish_option_structure(
        ticker="BOUND", underlying_price=Decimal("100"), technical_target=Decimal("108"),
        as_of=date(2026, 8, 12),
        contracts=[_c("BOUND260821C00103000", "2026-08-21", "103", str(bid), str(ask), oi=0, volume=1)],
        policy=aggressive_options_v2_policy(),
    )

    assert result["selected"] is not None
    assert result["policy"]["max_relative_spread"] == "0.35"
    assert result["evaluated_candidates"][0]["target_profit"] > 0
