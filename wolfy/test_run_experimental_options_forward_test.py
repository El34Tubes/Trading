from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path

import pytest


def test_cli_normalizes_chain_payload_shape(tmp_path: Path):
    from run_experimental_options_forward_test import load_chain_snapshot
    path = tmp_path / "chain.json"
    path.write_text(json.dumps({"fetched_at":"2026-08-12T20:00:00Z","source":"unit-read-only","chains":{"abc":[{"symbol":"ABC1"}]}}))
    snapshot = load_chain_snapshot(path)
    assert snapshot["source"] == "unit-read-only"
    assert snapshot["chains"] == {"ABC": [{"symbol":"ABC1"}]}
    assert snapshot["fetched_at"].tzinfo is timezone.utc


@pytest.mark.parametrize(
    "payload",
    [
        {"fetched_at": "2026-08-12T20:00:00", "chains": {}},
        {"fetched_at": "2026-08-12T20:00:00Z", "chains": []},
        {"fetched_at": "2026-08-12T20:00:00Z", "chains": {"ABC": {}}},
        {"fetched_at": "2026-08-12T20:00:00Z", "chains": {"ABC": ["bad"]}},
    ],
)
def test_cli_rejects_naive_snapshot_time_and_malformed_chain_containers(tmp_path, payload):
    from run_experimental_options_forward_test import load_chain_snapshot

    path = tmp_path / "chain.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="timezone|chains|sequence|mapping"):
        load_chain_snapshot(path)


def test_fetch_cboe_snapshots_is_bounded_to_qualifying_tickers(monkeypatch):
    from option_chain_provider import normalize_option_chain_snapshot
    from run_experimental_options_forward_test import fetch_cboe_snapshots

    called = []
    decision_at = __import__('datetime').datetime(2026,8,12,20,5,tzinfo=__import__('datetime').timezone.utc)

    def fake_acquire(ticker, *, signal_dt, decision_at):
        called.append(ticker)
        return normalize_option_chain_snapshot(
            {
                "ticker": ticker,
                "source": "cboe_public_delayed_options",
                "source_url": f"https://example.invalid/{ticker}",
                "fetched_at": __import__('datetime').datetime(2026,8,12,20,1,tzinfo=__import__('datetime').timezone.utc),
                "available_at": __import__('datetime').datetime(2026,8,12,20,1,tzinfo=__import__('datetime').timezone.utc),
                "market_at": __import__('datetime').datetime(2026,8,12,20,tzinfo=__import__('datetime').timezone.utc),
                "contracts": [{
                    "symbol": f"{ticker}260828C00100000", "option_type": "call",
                    "expiration": "2026-08-28", "strike": "100", "bid": "2",
                    "ask": "2.2", "bid_size": 1, "ask_size": 1, "volume": 1,
                    "open_interest": 10, "quote_at": "2026-08-12T20:00:00Z",
                    "market_date": "2026-08-12", "multiplier": 100,
                    "standard_contract": True,
                }],
            },
            requested_ticker=ticker, signal_dt=signal_dt, decision_at=decision_at,
        )

    monkeypatch.setattr("run_experimental_options_forward_test.acquire_option_chain_snapshot", fake_acquire)
    result = fetch_cboe_snapshots(
        ["abc", "XYZ", "abc"], signal_dt=__import__('datetime').date(2026,8,12),
        decision_at=decision_at,
    )
    assert called == ["ABC", "XYZ"]
    assert result["source"] == "cboe_public_delayed_options"
    assert sorted(result["chains"]) == ["ABC", "XYZ"]
    assert result["chains"]["ABC"].ticker == "ABC"


def test_cli_profile_choice_is_explicit_and_defaults_to_v1():
    from run_experimental_options_forward_test import build_parser

    parser = build_parser()
    common = ["--signal-dt", "2026-08-12", "--chain-json", "snapshot.json"]
    assert parser.parse_args(common).profile == "v1"
    assert parser.parse_args([*common, "--profile", "aggressive-v2"]).profile == "aggressive-v2"
    with pytest.raises(SystemExit):
        parser.parse_args([*common, "--profile", "unknown"])


def test_cli_rejects_naive_decision_time_and_preserves_explicit_aware_time():
    from run_experimental_options_forward_test import build_parser

    parser = build_parser()
    common = ["--signal-dt", "2026-08-12", "--chain-json", "snapshot.json"]
    with pytest.raises(SystemExit):
        parser.parse_args([*common, "--decision-time", "2026-08-12T20:05:00"])

    expected = "2026-08-12T16:05:00-04:00"
    args = parser.parse_args([*common, "--decision-time", expected])
    assert args.decision_time.isoformat() == expected
