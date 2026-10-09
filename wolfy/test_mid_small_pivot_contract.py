"""Contract baseline for the mid/small-cap multi-strategy pivot.

Reused baseline tests (captured 2026-09-17):
- test_test_db.py
- test_eod_readiness.py
- test_daily_evaluation_ledger.py

Production baseline query (read-only; captured with transaction_read_only=on):
    SELECT current_database(),
           (SELECT count(*) FROM strategies),
           (SELECT count(*) FROM recommendations),
           (SELECT count(*) FROM paper_trades);
Result: database=wolfy, strategies=7, recommendations=569, paper_trades=2.
"""

from dataclasses import FrozenInstanceError

import pytest

from daily_evaluation_ledger import DailyRunIdentity, create_daily_run
from eod_readiness import EODReadiness, evaluate_eod_readiness
from orchestration_config import MID_SMALL_PIVOT_POLICY
from test_db import TEST_DATABASE_NAME, resolve_test_dsn


def test_mid_small_pivot_policy_is_frozen_and_exact():
    policy = MID_SMALL_PIVOT_POLICY

    assert policy.version == "mid_small_multi_strategy_pivot_v1"
    assert policy.market_cap_min == 200_000_000
    assert policy.market_cap_max == 15_000_000_000
    assert policy.minimum_price == 3
    assert policy.adv_sessions == 20
    assert policy.minimum_average_dollar_volume == 5_000_000
    assert policy.benchmark_only == frozenset({"SPY", "IWM", "MDY"})
    assert policy.strategy_sleeves == (
        "trend_pullback_reclaim",
        "volatility_contraction_breakout",
        "close_confirmed_breakout",
    )
    assert policy.instrument_expressions == frozenset(
        {"long_call", "call_debit_spread", "underlying_stock_fallback"}
    )
    assert policy.maximum_positions == 20
    assert policy.risk_fraction_per_position == 0.05
    assert policy.maximum_aggregate_risk == 1.0
    assert policy.maximum_positions_per_sector == 5
    assert policy.paper_only is True
    assert policy.no_live_execution is True
    assert policy.broker_order_submitted is False

    with pytest.raises(FrozenInstanceError):
        policy.maximum_positions = 21


def test_pivot_reuses_isolated_database_readiness_and_daily_ledger_apis():
    assert TEST_DATABASE_NAME == "wolfy_test"
    assert callable(resolve_test_dsn)
    assert EODReadiness.__module__ == "eod_readiness"
    assert callable(evaluate_eod_readiness)
    assert DailyRunIdentity.__module__ == "daily_evaluation_ledger"
    assert callable(create_daily_run)
