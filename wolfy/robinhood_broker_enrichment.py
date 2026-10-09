#!/usr/bin/env python3
"""Robinhood MCP enrichment adapter for Wolfy paper recommendations.

This module is intentionally read-only and broker-safe. It does not import or
call any Robinhood order/cancel/exercise tools. It defines the deterministic
shape Wolfy expects from Robinhood MCP reads so recommendation code can store
broker context without weakening the no-live-execution guardrail.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

READ_ONLY_ROBINHOOD_TOOLS = (
    "get_accounts",
    "get_portfolio",
    "get_equity_positions",
    "get_option_positions",
    "get_equity_orders",
    "get_option_orders",
    "get_equity_quotes",
    "get_equity_price_book",
    "get_equity_historicals",
    "get_equity_fundamentals",
    "get_equity_tradability",
    "get_financials",
    "get_earnings_calendar",
    "get_earnings_results",
    "get_option_chains",
    "get_option_instruments",
    "get_option_quotes",
    "get_option_historicals",
)

BLOCKED_LIVE_ROBINHOOD_TOOLS = (
    "place_equity_order",
    "place_option_order",
    "cancel_equity_order",
    "cancel_option_order",
    "exercise_option",
    "cancel_option_exercise",
)


def make_read_only_enrichment_payload(
    ticker: str,
    *,
    tradability: Mapping[str, Any] | None = None,
    quote: Mapping[str, Any] | None = None,
    price_book: Mapping[str, Any] | None = None,
    fundamentals: Mapping[str, Any] | None = None,
    earnings: Mapping[str, Any] | None = None,
    account_exposure: Mapping[str, Any] | None = None,
    option_spread: Mapping[str, Any] | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Return the broker_enrichment mapping accepted by eod_signals.

    The caller may populate these fields from MCP tools after Robinhood tools
    are available in a fresh Hermes session. Keeping this as a pure formatter
    makes it testable without broker credentials and makes the read-only safety
    boundary obvious.
    """
    return {
        "ticker": ticker.upper(),
        "source": "robinhood_mcp",
        "read_only": True,
        "no_live_execution": True,
        "broker_order_submitted": False,
        "fetched_at": fetched_at or datetime.now(timezone.utc).isoformat(),
        "tradability": dict(tradability or {}),
        "quote": dict(quote or {}),
        "price_book": dict(price_book or {}),
        "fundamentals": dict(fundamentals or {}),
        "earnings": dict(earnings or {}),
        "account_exposure": dict(account_exposure or {}),
        "option_spread": dict(option_spread or {}),
        "read_only_tools_expected": list(READ_ONLY_ROBINHOOD_TOOLS),
        "blocked_live_tools": list(BLOCKED_LIVE_ROBINHOOD_TOOLS),
    }


def merge_ticker_payloads(*payloads: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Build the ticker-keyed mapping for write_approved_paper_recommendations."""
    merged: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        ticker = str(payload.get("ticker") or "").upper()
        if ticker:
            merged[ticker] = dict(payload)
    return merged
