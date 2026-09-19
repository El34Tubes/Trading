from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from eod_backtest import (
    StrategyBacktestSpec,
    build_chronological_splits,
    evaluate_setup_trade,
    run_multi_strategy_backtest,
)
from eod_monitoring import govern_research_backtest

UTC = timezone.utc


def _dt(day: int, hour: int = 21) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=UTC)


def _signal(*, strategy: str = "mid_small_trend_pullback_reclaim_v1", day: int = 2, sector: str = "Technology") -> dict:
    return {
        "strategy_id": strategy,
        "strategy_version": 1,
        "ticker": f"T{day}",
        "sector": sector,
        "regime": "risk_on",
        "signal_dt": date(2026, 1, day),
        "decision_at": _dt(day),
        "context_available_at": _dt(day, 20),
        "entry": "100",
        "stop": "95",
        "target": "107.5",
        "max_hold_days": 3,
    }


def _bars(day: int = 2, *, target: bool = True) -> list[dict]:
    high = "108" if target else "103"
    return [
        {
            "dt": date(2026, 1, day + 1),
            "open": "101",
            "high": high,
            "low": "96",
            "close": "102",
            "available_at": _dt(day + 1),
        }
    ]


def test_chronological_splits_are_anchored_or_rolling_purged_and_holdout_untouched():
    dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(20)]

    anchored = build_chronological_splits(
        dates, mode="anchored", train_size=6, test_size=3, purge_days=2, holdout_size=3
    )
    rolling = build_chronological_splits(
        dates, mode="rolling", train_size=6, test_size=3, purge_days=2, holdout_size=3
    )

    assert anchored.holdout == tuple(dates[-3:])
    assert rolling.holdout == tuple(dates[-3:])
    assert all(not (set(fold.train) | set(fold.test)) & set(anchored.holdout) for fold in anchored.folds)
    assert all((fold.test[0] - fold.train[-1]).days > 2 for fold in anchored.folds)
    assert len(anchored.folds[1].train) > len(anchored.folds[0].train)
    assert len(rolling.folds[1].train) == len(rolling.folds[0].train) == 6
    with pytest.raises(ValueError, match="chronological"):
        build_chronological_splits(list(reversed(dates)), mode="anchored", train_size=6, test_size=3)


def test_trade_evaluation_models_entry_modes_gaps_stop_first_costs_and_delisting():
    signal = _signal()
    same_bar = [
        {
            "dt": date(2026, 1, 3),
            "open": "101",
            "high": "109",
            "low": "94",
            "close": "108",
            "available_at": _dt(3),
        }
    ]
    stopped = evaluate_setup_trade(
        signal,
        same_bar,
        entry_mode="next_session_open",
        slippage_bps=Decimal("10"),
        commission=Decimal("1"),
    )
    reference = evaluate_setup_trade(signal, _bars(), entry_mode="eod_reference")
    gap = evaluate_setup_trade(
        signal,
        [{**same_bar[0], "open": "93", "high": "94", "low": "90", "close": "92"}],
        entry_mode="next_session_open",
    )
    delisted = evaluate_setup_trade(
        signal,
        [],
        entry_mode="eod_reference",
        delisting_return=Decimal("-1"),
    )

    assert stopped["exit_reason"] == "stop_first_same_bar"
    assert Decimal(stopped["net_r"]) < Decimal("-1")
    assert reference["entry_price"] == "100.0000"
    assert reference["exit_reason"] == "target"
    assert gap["exit_reason"] == "gap_through_stop"
    assert gap["exit_price"] == "93.0000"
    assert delisted["exit_reason"] == "delisting"
    assert delisted["net_return"] == "-1.0000"
    assert evaluate_setup_trade(signal, [], entry_mode="eod_reference")["status"] == "excluded_missing_bars"


def test_point_in_time_inputs_fail_closed_and_backtest_reports_native_metrics():
    late = _signal()
    late["context_available_at"] = late["decision_at"] + timedelta(seconds=1)
    with pytest.raises(ValueError, match="available_at"):
        evaluate_setup_trade(late, _bars(), entry_mode="eod_reference")
    with pytest.raises(ValueError, match="available_at"):
        evaluate_setup_trade(
            _signal(),
            [{**_bars()[0], "available_at": _dt(2) + timedelta(days=10)}],
            entry_mode="next_session_open",
        )

    strategies = [
        "mid_small_trend_pullback_reclaim_v1",
        "mid_small_volatility_contraction_breakout_v1",
        "close_confirmed_breakout_v1",
    ]
    signals = []
    for strategy_index, strategy in enumerate(strategies):
        for day in range(2, 9):
            row = _signal(
                strategy=strategy,
                day=day,
                sector="Technology" if day < 6 else "Health Care",
            )
            row["ticker"] = f"S{strategy_index}T{day}"
            signals.append(row)
    bars = {
        row["ticker"]: _bars(row["signal_dt"].day, target=row["signal_dt"].day != 5)
        for row in signals
    }
    specs = [
        StrategyBacktestSpec(
            strategy_id="mid_small_trend_pullback_reclaim_v1",
            strategy_version=1,
            entry_mode="next_session_open",
            split_mode="anchored",
            max_hold_days=3,
        ),
        StrategyBacktestSpec(
            strategy_id="mid_small_volatility_contraction_breakout_v1",
            strategy_version=1,
            entry_mode="eod_reference",
            split_mode="rolling",
            max_hold_days=3,
        ),
        StrategyBacktestSpec(
            strategy_id="close_confirmed_breakout_v1",
            strategy_version=1,
            entry_mode="eod_reference",
            split_mode="anchored",
            max_hold_days=10,
            preserve_approval=True,
        ),
    ]
    attempts = [
        {"family": "pullback", "parameters": {"atr": "0.5"}, "passed": False},
        {"family": "pullback", "parameters": {"atr": "0.75"}, "passed": True},
    ]

    report = run_multi_strategy_backtest(
        specs=specs,
        signals=signals,
        bars_by_ticker=bars,
        attempted_parameters=attempts,
        train_size=2,
        test_size=1,
        purge_days=0,
        holdout_size=1,
        confidence_block_days=2,
    )

    assert {row["strategy_id"] for row in report["strategies"]} == {
        "close_confirmed_breakout_v1",
        "mid_small_trend_pullback_reclaim_v1",
        "mid_small_volatility_contraction_breakout_v1",
    }
    required = {
        "sample_count", "hit_rate", "stop_rate", "expectancy_r", "max_drawdown_r",
        "mfe_r", "mae_r", "turnover", "median_holding_days", "sector_concentration",
        "regime_concentration", "date_clustered_confidence_interval", "sensitivity",
        "overlap",
    }
    assert all(required <= set(row["metrics"]) for row in report["strategies"])
    assert all(row["metrics"]["sample_count"] == 7 for row in report["strategies"])
    assert report["attempted_parameters"] == attempts
    assert report["holdout_opened_once"] is True
    assert report["point_in_time_joins"] is True
    assert report["outcome_semantics"] == "underlying_setup_only"


def test_governance_new_families_can_only_reach_candidate_and_approval_is_immutable():
    approved = {
        "paper_recommendation_approval": True,
        "approval_scope": "paper_only_no_live_execution",
        "approved_at": "2026-01-01T00:00:00+00:00",
        "approved_strategy_version": 1,
    }
    original = deepcopy(approved)

    pullback = govern_research_backtest(
        current_status="research_only",
        strategy_id="mid_small_trend_pullback_reclaim_v1",
        gate_passed=True,
        metadata=approved,
    )
    failed = govern_research_backtest(
        current_status="research_only",
        strategy_id="mid_small_volatility_contraction_breakout_v1",
        gate_passed=False,
        metadata={},
    )
    breakout = govern_research_backtest(
        current_status="approved",
        strategy_id="close_confirmed_breakout_v1",
        gate_passed=False,
        metadata=approved,
    )

    assert pullback["status"] == "candidate"
    assert pullback["paper_publication_authorized"] is False
    assert pullback["requires_explicit_user_approval"] is True
    assert failed["status"] == "research_only"
    assert breakout["status"] == "approved"
    assert breakout["metadata"] == original
    assert approved == original
