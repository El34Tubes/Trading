#!/usr/bin/env python3
"""Shared Wolfy orchestration constants.

This module is intentionally lightweight and side-effect free. Cron-facing
wrappers under /root/.hermes/scripts import these values so ticker universes,
shards, lookbacks, and readiness thresholds do not drift across jobs.
"""
from __future__ import annotations

from pathlib import Path

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
