from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from eod_backtest import run_portfolio_allocator_backtest
from portfolio_backtest import PortfolioBacktestCandidate, run_portfolio_backtest


def _candidate(
    ticker: str,
    *,
    day: int = 1,
    hold_days: int = 1,
    score: str = "10",
    sector: str = "Technology",
    strategy: str = "close_confirmed_breakout_v1",
    outcome_r: str = "1",
    expression: str = "underlying_stock_fallback",
    expression_cost_r: str = "0",
    regime: str = "risk_on",
) -> PortfolioBacktestCandidate:
    signal_dt = date(2026, 1, 1) + timedelta(days=day - 1)
    return PortfolioBacktestCandidate(
        ticker=ticker,
        strategy_id=strategy,
        strategy_version=1,
        sector=sector,
        score=Decimal(score),
        signal_dt=signal_dt,
        exit_dt=signal_dt + timedelta(days=hold_days),
        outcome_r=Decimal(outcome_r),
        expression=expression,
        expression_cost_r=Decimal(expression_cost_r),
        regime=regime,
    )


def test_replay_uses_allocator_caps_dedupe_open_carry_and_current_equity_sizing():
    candidates = [
        _candidate("DUP", score="100", sector="Technology", hold_days=3),
        _candidate("DUP", score="1", sector="Health Care", hold_days=3),
    ]
    candidates.extend(
        _candidate(f"T{index}", score=str(90 - index), sector="Technology", hold_days=3)
        for index in range(5)
    )
    candidates.append(_candidate("H0", score="80", sector="Health Care", hold_days=3))
    # Day two candidates see six carried positions; Technology is already at its cap.
    candidates.extend(
        [
            _candidate("T_BLOCKED", day=2, score="99", sector="Technology"),
            _candidate("H1", day=2, score="98", sector="Health Care", outcome_r="1"),
        ]
    )

    report = run_portfolio_backtest(candidates, starting_equity=Decimal("100000"), bootstrap_samples=20, seed=7)

    day_one = [row for row in report["allocations"] if row["signal_dt"] == "2026-01-01"]
    assert len([row for row in day_one if row["selected"]]) == 6
    assert len([row for row in day_one if row["ticker"] == "DUP" and row["selected"]]) == 1
    assert next(row for row in day_one if row["ticker"] == "DUP" and not row["selected"])["reason"] == "duplicate_ticker"
    blocked = next(row for row in report["allocations"] if row["ticker"] == "T_BLOCKED")
    assert blocked["reason"] == "sector_position_cap"
    h1 = next(row for row in report["trades"] if row["ticker"] == "H1")
    assert h1["risk_fraction"] == "0.0500"
    assert h1["risk_amount"] == "5000.0000"
    assert max(Decimal(row["aggregate_risk_fraction"]) for row in report["daily"]) <= Decimal("1")
    assert report["policy"] == {"maximum_positions": 20, "risk_fraction": "0.0500", "maximum_per_sector": 5, "maximum_aggregate_risk": "1.0000"}

    resized = run_portfolio_backtest(
        [
            _candidate("EARLY_LOSS", outcome_r="-1"),
            _candidate("RESIZED", day=2, sector="Health Care", outcome_r="1"),
        ],
        starting_equity=Decimal("100000"),
        bootstrap_samples=5,
    )
    resized_trade = next(row for row in resized["trades"] if row["ticker"] == "RESIZED")
    assert resized_trade["risk_amount"] == "4750.0000"


def test_correlated_losses_ruin_account_once_and_never_resurrect_it():
    sectors = ["Technology", "Health Care", "Industrials", "Energy"]
    candidates = [
        _candidate(f"LOSS{index:02d}", sector=sectors[index % 4], score=str(100 - index), outcome_r="-1")
        for index in range(20)
    ]
    candidates.append(_candidate("TOO_LATE", day=3, sector="Utilities", outcome_r="10"))

    report = run_portfolio_backtest(candidates, starting_equity=Decimal("100000"), bootstrap_samples=25, seed=11)

    assert report["ruin"]["occurred"] is True
    assert report["ruin"]["date"] == "2026-01-02"
    assert report["ruin"]["time_to_ruin_days"] == 1
    assert report["metrics"]["terminal_equity"] == "0.0000"
    assert report["metrics"]["max_drawdown"] == "-1.0000"
    assert not any(row["ticker"] == "TOO_LATE" and row["selected"] for row in report["allocations"])
    assert report["metrics"]["longest_loss_streak"] == 20
    assert report["metrics"]["worst_day"]["pnl"] == "-100000.0000"


def test_seeded_block_bootstrap_is_deterministic_and_expression_results_stay_separate():
    candidates = [
        _candidate("STOCK", day=1, sector="Technology", outcome_r="1", expression_cost_r="0.02"),
        _candidate("CALL", day=2, sector="Health Care", outcome_r="1", expression="long_call", expression_cost_r="0.10"),
        _candidate("SPREAD", day=3, sector="Industrials", outcome_r="-1", expression="call_debit_spread", expression_cost_r="0.05", regime="risk_off"),
    ]

    first = run_portfolio_backtest(candidates, starting_equity=Decimal("100000"), bootstrap_samples=40, block_days=2, seed=123)
    second = run_portfolio_backtest(list(reversed(candidates)), starting_equity=Decimal("100000"), bootstrap_samples=40, block_days=2, seed=123)

    assert first["ruin"]["bootstrap"] == second["ruin"]["bootstrap"]
    assert first["ruin"]["bootstrap"]["seed"] == 123
    assert first["ruin"]["bootstrap"]["samples"] == 40
    assert set(first["by_expression"]) == {"underlying_stock_fallback", "long_call", "call_debit_spread"}
    assert first["by_expression"]["underlying_stock_fallback"]["outcomes"] == 1
    assert first["by_expression"]["long_call"]["outcomes"] == 1
    assert first["by_expression"]["long_call"]["cost_r"] == "0.1000"
    assert first["outcome_labels_pooled"] is False
    assert set(first["by_strategy"]) == {"close_confirmed_breakout_v1"}
    assert set(first["by_sector"]) == {"Technology", "Health Care", "Industrials"}
    assert set(first["by_regime"]) == {"risk_on", "risk_off"}
    assert "block bootstrap resamples observed daily portfolio P&L" in first["model_limits"]
    assert run_portfolio_allocator_backtest(
        candidates, bootstrap_samples=40, block_days=2, seed=123
    )["ruin"]["bootstrap"] == first["ruin"]["bootstrap"]
