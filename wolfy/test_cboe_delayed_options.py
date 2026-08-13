from __future__ import annotations

from datetime import date, datetime, timezone


def test_normalize_cboe_delayed_chain_preserves_quotes_liquidity_and_greeks():
    from cboe_delayed_options import normalize_cboe_payload
    payload = {
        "timestamp": "2026-08-13 03:44:36",
        "data": {
            "symbol": "ABC", "current_price": 100.25, "bid": 100.2, "ask": 100.3,
            "options": [{
                "option": "ABC260828C00100000", "bid": 2.0, "ask": 2.2,
                "bid_size": 12, "ask_size": 15, "volume": 50, "open_interest": 500,
                "iv": 0.45, "delta": 0.55, "gamma": 0.03, "theta": -0.08,
                "vega": 0.12, "rho": 0.04, "last_trade_time": "2026-08-12T19:58:00",
            }],
        },
    }
    result = normalize_cboe_payload(payload, requested_ticker="abc")
    assert result["source"] == "cboe_public_delayed_options"
    assert result["delayed"] is True
    assert result["ticker"] == "ABC"
    assert result["underlying"]["price"] == "100.25"
    contract = result["contracts"][0]
    assert contract["symbol"] == "ABC260828C00100000"
    assert contract["option_type"] == "call"
    assert contract["expiration"] == "2026-08-28"
    assert contract["strike"] == "100"
    assert contract["bid"] == "2.0"
    assert contract["ask"] == "2.2"
    assert contract["open_interest"] == 500
    assert contract["delta"] == "0.55"
    assert contract["quote_at"] == "2026-08-13T03:44:36+00:00"
    assert contract["market_date"] == "2026-08-12"


def test_zero_cboe_iv_and_greeks_are_marked_unavailable_not_real_measurements():
    from cboe_delayed_options import normalize_cboe_payload
    payload = {"timestamp":"2026-08-13 03:44:36","data":{"symbol":"ABC","options":[{"option":"ABC260828C00050000","bid":50,"ask":51,"volume":1,"open_interest":1,"iv":0,"delta":1,"gamma":0,"theta":0,"vega":0,"rho":0}]}}
    contract = normalize_cboe_payload(payload, requested_ticker="ABC")["contracts"][0]
    assert contract["implied_volatility"] is None
    assert contract["greeks_available"] is False


def test_cboe_occ_parser_handles_puts_and_decimal_strikes():
    from cboe_delayed_options import parse_occ_symbol
    parsed = parse_occ_symbol("BRK.B260918P00412500")
    assert parsed == {"underlying":"BRK.B","expiration":date(2026,9,18),"option_type":"put","strike":"412.5"}
