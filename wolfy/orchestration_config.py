#!/usr/bin/env python3
"""Shared Wolfy orchestration constants.

This module is intentionally lightweight and side-effect free. Cron-facing
wrappers under /root/.hermes/scripts import these values so ticker universes,
shards, lookbacks, and readiness thresholds do not drift across jobs.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MidSmallPivotPolicy:
    """Canonical, side-effect-free contract for the paper-only pivot."""

    version: str
    market_cap_min: int
    market_cap_max: int
    minimum_price: int
    adv_sessions: int
    minimum_average_dollar_volume: int
    benchmark_only: frozenset[str]
    strategy_sleeves: tuple[str, ...]
    instrument_expressions: frozenset[str]
    maximum_positions: int
    risk_fraction_per_position: float
    maximum_aggregate_risk: float
    maximum_positions_per_sector: int
    paper_only: bool
    no_live_execution: bool
    broker_order_submitted: bool


MID_SMALL_PIVOT_POLICY = MidSmallPivotPolicy(
    version="mid_small_multi_strategy_pivot_v1",
    market_cap_min=200_000_000,
    market_cap_max=15_000_000_000,
    minimum_price=3,
    adv_sessions=20,
    minimum_average_dollar_volume=5_000_000,
    benchmark_only=frozenset({"SPY", "IWM", "MDY"}),
    strategy_sleeves=(
        "trend_pullback_reclaim",
        "volatility_contraction_breakout",
        "close_confirmed_breakout",
    ),
    instrument_expressions=frozenset(
        {"long_call", "call_debit_spread", "underlying_stock_fallback"}
    ),
    maximum_positions=20,
    risk_fraction_per_position=0.05,
    maximum_aggregate_risk=1.0,
    maximum_positions_per_sector=5,
    paper_only=True,
    no_live_execution=True,
    broker_order_submitted=False,
)

HERMES_DIR = Path("/root/.hermes")
WOLFY_DIR = HERMES_DIR / "wolfy"
SCRIPTS_DIR = HERMES_DIR / "scripts"

DEFAULT_EOD_SOURCE = "massive"
DEFAULT_EOD_LOOKBACK_DAYS = 730
DRY_RUN_EOD_LOOKBACK_DAYS = 30
DEPTH_READY_BARS = 495

CORE_EOD_UNIVERSE = (
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "XLK",
    "XLF",
    "XLY",
    "XLI",
    "XLE",
    "XLV",
    "XLP",
    "XLU",
    "XLB",
    "XLRE",
    "XLC",
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "TSLA",
    "AVGO",
    "JPM",
    "LLY",
    "V",
    "UNH",
    "COST",
    "NFLX",
    "AMD",
    "ORCL",
    "CRM",
    "PANW",
    "SMH",
)

DRY_RUN_EOD_UNIVERSE = ("SPY", "QQQ", "IWM")

EOD_INGEST_SHARDS = {
    1: ("SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLY", "XLI", "XLE"),
    2: ("XLV", "XLP", "XLU", "XLB", "XLRE", "XLC", "AAPL", "MSFT", "NVDA"),
    3: ("AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "LLY", "V"),
    4: ("UNH", "COST", "NFLX", "AMD"),
    5: ("ORCL", "CRM", "PANW", "SMH"),
}


def tickers_csv(tickers: tuple[str, ...] | list[str]) -> str:
    """Return a normalized comma-separated ticker list."""
    return ",".join(str(t).strip().upper() for t in tickers if str(t).strip())


def parse_tickers(tickers_csv_value: str | None, *, default: tuple[str, ...]) -> list[str]:
    """Parse comma-separated tickers, falling back to a configured default."""
    raw = tickers_csv_value or tickers_csv(default)
    return [ticker.strip().upper() for ticker in raw.split(",") if ticker.strip()]
