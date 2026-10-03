from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from setup_evaluators import (
    TREND_PULLBACK_STRATEGY_ID,
    TREND_PULLBACK_STRATEGY_VERSION,
    TrendPullbackFacts,
    evaluate_trend_pullback,
)

UTC = timezone.utc
DECISION_AT = datetime(2099, 4, 6, 20, tzinfo=UTC)


def _facts(**overrides) -> TrendPullbackFacts:
    values = {
        "ticker": "ZZPULL",
        "sector": "Industrials",
        "decision_at": DECISION_AT,
        "evaluated_at": DECISION_AT + timedelta(minutes=5),
        "features_available_at": DECISION_AT - timedelta(minutes=1),
        "universe_eligible": True,
        "close": "51.00",
        "prior_day_high": "50.50",
        "sma_20": "50.00",
        "sma_50": "46.00",
        "sma_50_20_sessions_ago": "44.00",
        "sma_200": "40.00",
        "atr_14": "2.00",
        "pullback_sessions": 4,
        "pullback_low": "49.00",
        "swing_low": "48.50",
        "pullback_average_volume": 800_000,
        "average_volume_20d": 1_000_000,
        "reclaim_trigger": "close_above_prior_day_high",
        "event_landmine": False,
        "risk_veto": False,
        "benchmark_context": {
            ticker: {
                "return_20d": value,
                "available_at": (DECISION_AT - timedelta(minutes=2)).isoformat(),
            }
            for ticker, value in {"SPY": "0.02", "IWM": "0.01", "MDY": "0.015"}.items()
        },
        "source_fingerprint": "a" * 64,
        "provenance": {"feature_row_id": 17},
    }
    values.update(overrides)
    return TrendPullbackFacts(**values)


def test_pullback_passes_frozen_rules_and_emits_research_candidate_terms():
    result = evaluate_trend_pullback(_facts())

    assert result.evaluation.passed is True
    assert result.evaluation.strategy_id == TREND_PULLBACK_STRATEGY_ID == "mid_small_trend_pullback_reclaim_v1"
    assert result.evaluation.strategy_version == TREND_PULLBACK_STRATEGY_VERSION == "research-v1"
    assert result.evaluation.gate_facts["governance_status"] == "research_only"
    assert result.evaluation.gate_facts["benchmark_context_only"] == ["IWM", "MDY", "SPY"]
    assert result.entry == Decimal("51.00")
    assert result.stop == Decimal("48.50")
    assert result.target == Decimal("56.00")
    assert len(result.facts_hash) == 64


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"sma_50": "39.00"}, "trend_failed"),
        ({"sma_50_20_sessions_ago": "46.00"}, "trend_failed"),
        ({"pullback_sessions": 1}, "pullback_shape_failed"),
        ({"pullback_sessions": 8}, "pullback_shape_failed"),
        (
            {"pullback_low": "46.50", "swing_low": "46.00", "sma_20": "50", "atr_14": "2"},
            "pullback_shape_failed",
        ),
        ({"pullback_low": "45.99", "swing_low": "45.50"}, "trend_failed"),
        ({"pullback_average_volume": 1_000_000}, "volume_failed"),
        ({"close": "50.25"}, "reclaim_not_confirmed"),
        ({"swing_low": "46.50"}, "stop_risk_too_wide"),
        ({"event_landmine": True}, "event_landmine"),
        ({"risk_veto": True}, "security_ineligible"),
    ],
)
def test_pullback_fails_each_frozen_gate(overrides, reason):
    result = evaluate_trend_pullback(_facts(**overrides))

    assert result.evaluation.passed is False
    assert result.evaluation.terminal_reason == reason
    assert result.entry is None and result.stop is None and result.target is None


def test_reclaim_variants_are_predeclared_and_deterministic():
    above_20dma = evaluate_trend_pullback(
        _facts(reclaim_trigger="close_above_20dma", close="50.25")
    )
    prior_high = evaluate_trend_pullback(_facts(close="50.25"))

    assert above_20dma.evaluation.passed is True
    assert prior_high.evaluation.terminal_reason == "reclaim_not_confirmed"
    with pytest.raises(ValueError, match="reclaim_trigger"):
        evaluate_trend_pullback(_facts(reclaim_trigger="intraday_touch"))


@pytest.mark.parametrize(
    "overrides",
    [
        {"decision_at": datetime(2099, 4, 6, 20)},
        {"features_available_at": DECISION_AT + timedelta(seconds=1)},
        {"benchmark_context": {}},
        {
            "benchmark_context": {
                ticker: {
                    "return_20d": "0.01",
                    "available_at": (DECISION_AT + timedelta(seconds=1)).isoformat(),
                }
                for ticker in ("SPY", "IWM", "MDY")
            }
        },
        {"pullback_sessions": True},
        {"event_landmine": 0},
        {"risk_veto": None},
    ],
)
def test_pullback_rejects_non_point_in_time_or_malformed_inputs(overrides):
    with pytest.raises(ValueError):
        evaluate_trend_pullback(_facts(**overrides))


def test_pullback_seed_is_research_only_and_cannot_auto_approve():
    from eod_signals import DEFAULT_STRATEGIES

    seed = next(item for item in DEFAULT_STRATEGIES if item[0] == TREND_PULLBACK_STRATEGY_ID)
    assert seed[1] == "trend_pullback_reclaim"
    assert seed[2]["strategy_version"] == TREND_PULLBACK_STRATEGY_VERSION
    assert seed[2]["requires_backtest"] is True
    assert seed[2]["requires_explicit_user_approval"] is True
    assert "research_only" in seed[3]
