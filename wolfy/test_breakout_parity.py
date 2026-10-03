from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from setup_evaluators import ApprovedBreakoutFacts, evaluate_approved_breakout

UTC = timezone.utc
EVALUATED_AT = datetime(2099, 2, 4, 22, tzinfo=UTC)


def _facts(**overrides) -> ApprovedBreakoutFacts:
    values = {
        "ticker": "ZZPARITY",
        "sector": "Industrials",
        "evaluated_at": EVALUATED_AT,
        "universe_eligible": True,
        "close": "105",
        "high": "106",
        "prior_five_high": "100",
        "prior_five_low": "100",
        "sma_fast": "95",
        "sma_slow": "90",
        "volume_ratio": "1.20",
        "atr": "3",
        "ticker_return_20d": "0.08",
        "spy_return_20d": "0.05",
        "spy_close": "510",
        "spy_sma_50": "500",
        "source_fingerprint": "a" * 64,
        "provenance": {"price_row_id": 7, "feature_row_id": 8},
        "benchmark_context": {
            "IWM": {"return_20d": "-0.20"},
            "MDY": {"return_20d": "0.30"},
        },
    }
    values.update(overrides)
    return ApprovedBreakoutFacts(**values)


def _legacy_passes(facts: ApprovedBreakoutFacts) -> bool:
    close = Decimal(str(facts.close))
    high = Decimal(str(facts.high))
    prior_high = Decimal(str(facts.prior_five_high))
    prior_low = Decimal(str(facts.prior_five_low))
    fast = Decimal(str(facts.sma_fast)) if facts.sma_fast is not None else None
    slow = Decimal(str(facts.sma_slow)) if facts.sma_slow is not None else None
    ticker_return = Decimal(str(facts.ticker_return_20d))
    spy_return = Decimal(str(facts.spy_return_20d))
    return all(
        (
            facts.universe_eligible,
            Decimal(str(facts.spy_close)) > Decimal(str(facts.spy_sma_50)),
            fast is None or close > fast,
            fast is None or slow is None or fast >= slow,
            close > prior_high,
            ticker_return > spy_return,
            ticker_return - spy_return >= Decimal("0.02"),
            Decimal(str(facts.volume_ratio)) >= Decimal("1.2"),
            (close - prior_low) / close <= Decimal("0.05"),
            close >= max(high, prior_high) * Decimal("0.95"),
        )
    )


@pytest.mark.parametrize(
    "overrides,expected_reason",
    [
        ({}, "passed"),
        ({"sma_fast": None, "sma_slow": None}, "passed"),
        ({"universe_eligible": False}, "security_ineligible"),
        ({"spy_close": "500"}, "market_regime_failed"),
        ({"sma_fast": "106"}, "trend_failed"),
        ({"close": "100"}, "breakout_not_confirmed"),
        ({"ticker_return_20d": "0.069"}, "relative_strength_failed"),
        ({"volume_ratio": "1.19"}, "volume_failed"),
        ({"prior_five_low": "90"}, "stop_risk_too_wide"),
        ({"high": "120"}, "overextended"),
    ],
)
def test_approved_breakout_adapter_has_golden_pass_fail_parity(overrides, expected_reason):
    facts = _facts(**overrides)

    result = evaluate_approved_breakout(facts)

    assert result.evaluation.passed is _legacy_passes(facts)
    assert result.evaluation.terminal_reason == expected_reason
    assert result.evaluation.strategy_id == "liquid_rs_breakout_close_confirm_1r"
    assert result.evaluation.gate_facts["approved_rules"]["max_hold_days"] == 10


def test_approved_breakout_adapter_preserves_entry_invalidation_target_and_raw_facts():
    result = evaluate_approved_breakout(_facts())

    assert result.entry == Decimal("105")
    assert result.stop == Decimal("100")
    assert result.target == Decimal("110")
    assert result.evaluation.metrics == {
        "atr": "3",
        "atr_pct": str(Decimal("3") / Decimal("105")),
        "prior_5d_high": "100",
        "prior_5d_low": "100",
        "rs_excess_20d": "0.03",
        "spy_return_20d": "0.05",
        "stop_risk_pct": str(Decimal("5") / Decimal("105")),
        "ticker_return_20d": "0.08",
        "vol_ratio": "1.20",
    }
    assert len(result.facts_hash) == 64
    assert result.facts_hash == evaluate_approved_breakout(_facts()).facts_hash


def test_iwm_and_mdy_context_cannot_change_the_approved_breakout_decision():
    baseline = evaluate_approved_breakout(_facts())
    changed = evaluate_approved_breakout(
        replace(
            _facts(),
            benchmark_context={
                "IWM": {"return_20d": "99"},
                "MDY": {"return_20d": "-99"},
            },
        )
    )

    assert changed.evaluation.passed is baseline.evaluation.passed
    assert changed.entry == baseline.entry
    assert changed.stop == baseline.stop
    assert changed.target == baseline.target
    assert changed.evaluation.gate_facts["benchmark_context_only"] == ("IWM", "MDY")
