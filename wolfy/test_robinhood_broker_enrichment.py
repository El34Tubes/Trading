from __future__ import annotations


def test_robinhood_enrichment_payload_is_read_only_and_ticker_keyed():
    from robinhood_broker_enrichment import make_read_only_enrichment_payload, merge_ticker_payloads

    payload = make_read_only_enrichment_payload(
        "aapl",
        tradability={"tradable": True, "halted": False},
        quote={"last_price": "200.00", "bid_price": "199.95", "ask_price": "200.05"},
        account_exposure={"existing_equity_position": True},
        option_spread={"available": False},
        fetched_at="2099-02-05T00:00:00Z",
    )
    merged = merge_ticker_payloads(payload)

    assert payload["source"] == "robinhood_mcp"
    assert payload["read_only"] is True
    assert payload["no_live_execution"] is True
    assert payload["broker_order_submitted"] is False
    assert "place_equity_order" in payload["blocked_live_tools"]
    assert "cancel_option_order" in payload["blocked_live_tools"]
    assert all(not tool.startswith(("place_", "cancel_", "exercise_")) for tool in payload["read_only_tools_expected"])
    assert merged["AAPL"]["quote"]["last_price"] == "200.00"
