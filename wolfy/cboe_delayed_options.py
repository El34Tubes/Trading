"""Free read-only adapter for Cboe public delayed option-chain snapshots."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Mapping
from zoneinfo import ZoneInfo

SOURCE = "cboe_public_delayed_options"
URL_TEMPLATE = "https://cdn.cboe.com/api/global/delayed_quotes/options/{ticker}.json"
_OCC = re.compile(r"^(?P<underlying>.+?)(?P<expiry>\d{6})(?P<kind>[CP])(?P<strike>\d{8})$")


def _text_decimal(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(Decimal(str(value)))


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
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_cboe_payload(payload: Mapping[str, Any], *, requested_ticker: str) -> dict[str, Any]:
    fetched_at = _snapshot_time(payload.get("timestamp"))
    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
    ticker = str(data.get("symbol") or payload.get("symbol") or requested_ticker).upper()
    contracts: list[dict[str, Any]] = []
    for raw in data.get("options", []):
        if not isinstance(raw, Mapping):
            continue
        try:
            parsed = parse_occ_symbol(str(raw.get("option") or ""))
        except ValueError:
            continue
        iv = Decimal(str(raw.get("iv") or 0))
        # Cboe commonly emits zero IV/Greeks for deep contracts where analytics
        # are unavailable. Do not mislabel those placeholders as measurements.
        greeks_available = iv > 0 and any(Decimal(str(raw.get(key) or 0)) != 0 for key in ("gamma", "theta", "vega", "rho"))
        contracts.append({
            "symbol": str(raw["option"]), "option_type": parsed["option_type"],
            "expiration": parsed["expiration"].isoformat(), "strike": parsed["strike"],
            "bid": _text_decimal(raw.get("bid")), "ask": _text_decimal(raw.get("ask")),
            "bid_size": int(raw.get("bid_size") or 0), "ask_size": int(raw.get("ask_size") or 0),
            "volume": int(raw.get("volume") or 0), "open_interest": int(raw.get("open_interest") or 0),
            "implied_volatility": str(iv) if iv > 0 else None,
            "delta": _text_decimal(raw.get("delta")) if greeks_available else None,
            "gamma": _text_decimal(raw.get("gamma")) if greeks_available else None,
            "theta": _text_decimal(raw.get("theta")) if greeks_available else None,
            "vega": _text_decimal(raw.get("vega")) if greeks_available else None,
            "rho": _text_decimal(raw.get("rho")) if greeks_available else None,
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
            "price": _text_decimal(data.get("current_price")), "bid": _text_decimal(data.get("bid")),
            "ask": _text_decimal(data.get("ask")), "last_trade_time": data.get("last_trade_time"),
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
