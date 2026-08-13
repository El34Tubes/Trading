from __future__ import annotations

import json
from datetime import date
from pathlib import Path


def test_cli_normalizes_chain_payload_shape(tmp_path: Path):
    from run_experimental_options_forward_test import load_chain_snapshot
    path = tmp_path / "chain.json"
    path.write_text(json.dumps({"fetched_at":"2026-08-12T20:00:00Z","source":"unit-read-only","chains":{"abc":[{"symbol":"ABC1"}]}}))
    snapshot = load_chain_snapshot(path)
    assert snapshot["source"] == "unit-read-only"
    assert snapshot["chains"] == {"ABC": [{"symbol":"ABC1"}]}


def test_fetch_cboe_snapshots_is_bounded_to_qualifying_tickers(monkeypatch):
    from run_experimental_options_forward_test import fetch_cboe_snapshots
    called = []
    def fake_fetch(ticker):
        called.append(ticker)
        return {"ticker":ticker,"source":"cboe_public_delayed_options","fetched_at":__import__('datetime').datetime(2026,8,12,20,tzinfo=__import__('datetime').timezone.utc),"contracts":[{"symbol":ticker+'1'}]}
    monkeypatch.setattr("run_experimental_options_forward_test.fetch_cboe_delayed_chain", fake_fetch)
    result = fetch_cboe_snapshots(["abc", "XYZ", "abc"])
    assert called == ["ABC", "XYZ"]
    assert result["source"] == "cboe_public_delayed_options"
    assert sorted(result["chains"]) == ["ABC", "XYZ"]
