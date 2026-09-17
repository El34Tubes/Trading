"""Free read-only adapter for Cboe public delayed option-chain snapshots."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from options_structure_selector import (
    strict_aware_datetime,
    strict_bounded_nonnegative_integer,
    strict_finite_decimal,
    strict_mapping,
    strict_mapping_sequence,
)

SOURCE = "cboe_public_delayed_options"
URL_TEMPLATE = "https://cdn.cboe.com/api/global/delayed_quotes/options/{ticker}.json"
_OCC = re.compile(r"^(?P<underlying>.+?)(?P<expiry>\d{6})(?P<kind>[CP])(?P<strike>\d{8})$")


def _text_decimal(value: Any, *, field: str, required: bool = False) -> str | None:
    if value is None or value == "":
        if required:
            raise ValueError(f"{field} must be a finite decimal")
        return None
    return str(strict_finite_decimal(value, field=field))


def parse_occ_symbol(symbol: str) -> dict[str, Any]:
    match = _OCC.match(symbol.strip().upper())
    if not match:
        raise ValueError(f"unrecognized OCC option symbol: {symbol}")
    expiration = datetime.strptime(match.group("expiry"), "%y%m%d").date()
    strike = Decimal(match.group("strike")) / Decimal("1000")
    strike_text = format(strike.normalize(), "f")
    if "." in strike_text:
        strike_text = strike_text.rstrip("0").rstrip(".")
    return {
        "underlying": match.group("underlying"), "expiration": expiration,
        "option_type": "call" if match.group("kind") == "C" else "put",
        "strike": strike_text,
    }


def _snapshot_time(value: Any) -> datetime:
    try:
        return strict_aware_datetime(value, field="timestamp").astimezone(timezone.utc)
    except ValueError as exc:
        raise ValueError("timestamp must be a timezone-aware datetime") from exc


def _optional_decimal(raw: Mapping[str, Any], field: str) -> Decimal:
    value = raw.get(field)
    if value is None or value == "":
        return Decimal("0")
    return strict_finite_decimal(value, field=field)


def normalize_cboe_payload(payload: Mapping[str, Any], *, requested_ticker: str) -> dict[str, Any]:
    payload = strict_mapping(payload, field="payload")
    fetched_at = _snapshot_time(payload.get("timestamp"))
    data = strict_mapping(payload.get("data"), field="payload data")
    options = strict_mapping_sequence(data.get("options"), field="payload options")

    ticker = str(data.get("symbol") or payload.get("symbol") or requested_ticker).upper()
    contracts: list[dict[str, Any]] = []
    for raw in options:
        try:
            parsed = parse_occ_symbol(str(raw.get("option") or ""))
        except ValueError:
            continue
        bid = _text_decimal(raw.get("bid"), field="bid", required=True)
        ask = _text_decimal(raw.get("ask"), field="ask", required=True)
        bid_size = strict_bounded_nonnegative_integer(
            raw.get("bid_size", 0), field="bid_size"
        )
        ask_size = strict_bounded_nonnegative_integer(
            raw.get("ask_size", 0), field="ask_size"
        )
        volume = strict_bounded_nonnegative_integer(raw.get("volume"), field="volume")
        open_interest = strict_bounded_nonnegative_integer(
            raw.get("open_interest"), field="open_interest"
        )
        iv = _optional_decimal(raw, "iv")
        greeks = {
            key: _optional_decimal(raw, key)
            for key in ("delta", "gamma", "theta", "vega", "rho")
        }
        # Cboe commonly emits zero IV/Greeks for deep contracts where analytics
        # are unavailable. Do not mislabel those placeholders as measurements.
        greeks_available = iv > 0 and any(
            greeks[key] != 0 for key in ("gamma", "theta", "vega", "rho")
        )
        contracts.append({
            "symbol": str(raw["option"]), "option_type": parsed["option_type"],
            "expiration": parsed["expiration"].isoformat(), "strike": parsed["strike"],
            "bid": bid, "ask": ask,
            "bid_size": bid_size, "ask_size": ask_size,
            "volume": volume, "open_interest": open_interest,
            "implied_volatility": str(iv) if iv > 0 else None,
            "delta": str(greeks["delta"]) if greeks_available else None,
            "gamma": str(greeks["gamma"]) if greeks_available else None,
            "theta": str(greeks["theta"]) if greeks_available else None,
            "vega": str(greeks["vega"]) if greeks_available else None,
            "rho": str(greeks["rho"]) if greeks_available else None,
            "greeks_available": greeks_available,
            "quote_at": fetched_at.isoformat(),
            "market_date": fetched_at.astimezone(ZoneInfo("America/New_York")).date().isoformat(),
            "last_trade_time": raw.get("last_trade_time"),
            "multiplier": 100, "standard_contract": True,
            "source": SOURCE, "source_url": URL_TEMPLATE.format(ticker=urllib.parse.quote(ticker, safe="")), "delayed": True,
        })
    return {
        "ticker": ticker, "source": SOURCE, "source_url": URL_TEMPLATE.format(ticker=urllib.parse.quote(ticker, safe="")),
        "delayed": True, "fetched_at": fetched_at, "contracts": contracts,
        "underlying": {
            "price": _text_decimal(data.get("current_price"), field="current_price"),
            "bid": _text_decimal(data.get("bid"), field="underlying_bid"),
            "ask": _text_decimal(data.get("ask"), field="underlying_ask"),
            "last_trade_time": data.get("last_trade_time"),
        },
    }


def fetch_cboe_delayed_chain(ticker: str, *, timeout: int = 30) -> dict[str, Any]:
    symbol = ticker.upper().strip()
    if not symbol:
        raise ValueError("ticker is required")
    url = URL_TEMPLATE.format(ticker=urllib.parse.quote(symbol, safe=""))
    request = urllib.request.Request(url, headers={"User-Agent": "Wolfy-EOD-Research/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return normalize_cboe_payload(payload, requested_ticker=symbol)
