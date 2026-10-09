from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import pytest


SIGNAL_DT = date(2026, 9, 17)
DECISION_AT = datetime(2026, 9, 17, 20, 5, tzinfo=timezone.utc)
QUOTE_AT = datetime(2026, 9, 17, 20, 0, tzinfo=timezone.utc)


def _contract(symbol: str = "ABC261016C00100000") -> dict[str, object]:
    return {
        "symbol": symbol,
        "option_type": "call",
        "expiration": "2026-10-16",
        "strike": "100",
        "bid": "2.00",
        "ask": "2.20",
        "bid_size": 10,
        "ask_size": 12,
        "volume": 50,
        "open_interest": 500,
        "quote_at": QUOTE_AT.isoformat(),
        "market_date": SIGNAL_DT.isoformat(),
        "multiplier": 100,
        "standard_contract": True,
    }


def _raw(*, ticker: str = "ABC", contracts=None) -> dict[str, object]:
    return {
        "ticker": ticker,
        "source": "unit_read_only",
        "source_url": "https://example.invalid/read-only/ABC",
        "fetched_at": DECISION_AT - timedelta(minutes=1),
        "available_at": DECISION_AT - timedelta(seconds=30),
        "market_at": QUOTE_AT,
        "contracts": [_contract()] if contracts is None else contracts,
    }


def test_normalized_snapshot_is_exact_immutable_and_hash_stable():
    from option_chain_provider import normalize_option_chain_snapshot

    first = normalize_option_chain_snapshot(
        _raw(), requested_ticker="abc", signal_dt=SIGNAL_DT, decision_at=DECISION_AT
    )
    second = normalize_option_chain_snapshot(
        _raw(), requested_ticker="ABC", signal_dt=SIGNAL_DT, decision_at=DECISION_AT
    )

    assert first.ticker == "ABC"
    assert first.provider == "unit_read_only"
    assert first.payload_sha256 == second.payload_sha256
    assert first.snapshot_id == second.snapshot_id
    assert len(first.payload_sha256) == 64
    assert first.contracts[0]["symbol"] == "ABC261016C00100000"
    with pytest.raises(TypeError):
        first.contracts[0]["bid"] = "99"  # type: ignore[index]
    assert first.paper_only is True
    assert first.no_live_execution is True


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda row: row.update(ticker="OTHER"), "ticker mismatch"),
        (lambda row: row.update(contracts=[]), "must not be empty"),
        (lambda row: row.update(contracts={}), "sequence"),
        (lambda row: row.update(contracts=["bad"]), "sequence"),
        (lambda row: row["contracts"][0].pop("expiration"), "expiration"),
        (lambda row: row.update(contracts=[_contract(), _contract()]), "duplicate"),
        (lambda row: row.update(contracts=[_contract("OTHER261016C00100000")]), "underlying mismatch"),
        (lambda row: row.update(contracts=[{**_contract(), "quote_at": "2026-09-17T20:00:00"}]), "timezone-aware"),
        (lambda row: row.update(contracts=[{**_contract(), "quote_at": DECISION_AT + timedelta(seconds=1)}]), "after decision"),
        (lambda row: row.update(contracts=[{**_contract(), "quote_at": DECISION_AT - timedelta(minutes=31)}]), "stale"),
        (lambda row: row.update(contracts=[{**_contract(), "market_date": "2026-09-16"}]), "market date"),
        (lambda row: row.update(available_at=DECISION_AT + timedelta(seconds=1)), "available_at"),
    ],
)
def test_snapshot_fails_closed_on_inexact_stale_or_partial_chain(mutate, match):
    from option_chain_provider import normalize_option_chain_snapshot

    raw = deepcopy(_raw())
    mutate(raw)
    with pytest.raises(ValueError, match=match):
        normalize_option_chain_snapshot(
            raw, requested_ticker="ABC", signal_dt=SIGNAL_DT, decision_at=DECISION_AT
        )


@pytest.mark.parametrize("field", ["fetched_at", "available_at", "market_at"])
def test_snapshot_rejects_naive_provenance_timestamps(field):
    from option_chain_provider import normalize_option_chain_snapshot

    raw = _raw()
    raw[field] = "2026-09-17T20:00:00"
    with pytest.raises(ValueError, match="timezone-aware"):
        normalize_option_chain_snapshot(
            raw, requested_ticker="ABC", signal_dt=SIGNAL_DT, decision_at=DECISION_AT
        )


@pytest.mark.parametrize(("field", "value"), [("volume", -1), ("open_interest", 2_147_483_648)])
def test_snapshot_rejects_invalid_bounded_liquidity(field, value):
    from option_chain_provider import normalize_option_chain_snapshot

    raw = _raw(contracts=[{**_contract(), field: value}])
    with pytest.raises(ValueError, match=field):
        normalize_option_chain_snapshot(
            raw, requested_ticker="ABC", signal_dt=SIGNAL_DT, decision_at=DECISION_AT
        )


def test_acquisition_uses_priority_and_only_falls_through_on_outage():
    from option_chain_provider import (
        OptionChainProviderUnavailable,
        ReadOnlyChainSource,
        acquire_option_chain_snapshot,
    )

    calls: list[str] = []

    def unavailable(ticker: str):
        calls.append(f"primary:{ticker}")
        raise OptionChainProviderUnavailable("offline")

    def fallback(ticker: str):
        calls.append(f"fallback:{ticker}")
        return _raw(ticker=ticker)

    snapshot = acquire_option_chain_snapshot(
        "abc",
        signal_dt=SIGNAL_DT,
        decision_at=DECISION_AT,
        sources=(
            ReadOnlyChainSource("primary", 10, unavailable),
            ReadOnlyChainSource("fallback", 20, fallback),
        ),
    )
    assert snapshot.provider == "unit_read_only"
    assert calls == ["primary:ABC", "fallback:ABC"]


def test_read_only_source_surface_has_no_broker_write_operations():
    import option_chain_provider as provider

    assert provider.READ_ONLY_OPERATIONS == frozenset({"fetch_chain"})
    source = provider.cboe_delayed_source()
    assert callable(source.fetch_chain)
    for forbidden in ("place_order", "cancel_order", "replace_order", "exercise", "move_money"):
        assert not hasattr(source, forbidden)
