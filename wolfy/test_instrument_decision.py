from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import uuid

import pytest

from instrument_decision import InstrumentDecisionError, decide_instrument
from option_chain_provider import OptionChainSnapshot, normalize_option_chain_snapshot
from portfolio_allocator import PortfolioCandidate


DECISION_AT = datetime(2026, 9, 17, 20, 5, tzinfo=timezone.utc)
SIGNAL_DT = date(2026, 9, 17)


def _candidate(*, ticker: str = "XYZ", target: str = "110") -> PortfolioCandidate:
    return PortfolioCandidate(
        candidate_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        universe_snapshot_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        ticker=ticker,
        strategy_id="liquid_rs_breakout_close_confirm_1r",
        strategy_version="approved-2026-08-03",
        sector="Industrials",
        score=Decimal("2"),
        entry=Decimal("100"),
        stop=Decimal("95"),
        target=Decimal(target),
    )


def _contract(
    strike: str,
    bid: str,
    ask: str,
    *,
    symbol: str | None = None,
    oi: int = 500,
    volume: int = 50,
) -> dict:
    strike_code = f"{int(Decimal(strike) * 1000):08d}"
    return {
        "symbol": symbol or f"XYZ261002C{strike_code}",
        "option_type": "call",
        "expiration": "2026-10-02",
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "bid_size": 10,
        "ask_size": 10,
        "open_interest": oi,
        "volume": volume,
        "implied_volatility": "0.40",
        "quote_at": "2026-09-17T20:00:00+00:00",
        "market_date": "2026-09-17",
        "multiplier": 100,
        "standard_contract": True,
    }


def _snapshot(*contracts: dict, ticker: str = "XYZ") -> OptionChainSnapshot:
    return normalize_option_chain_snapshot(
        {
            "ticker": ticker,
            "source": "cboe_public_delayed_options",
            "source_url": f"https://example.invalid/{ticker}",
            "fetched_at": "2026-09-17T20:01:00+00:00",
            "market_at": "2026-09-17T20:00:00+00:00",
            "available_at": "2026-09-17T20:02:00+00:00",
            "contracts": list(contracts),
        },
        requested_ticker=ticker,
        signal_dt=SIGNAL_DT,
        decision_at=DECISION_AT,
    )


def _copy_snapshot(
    snapshot: OptionChainSnapshot, **changes
) -> OptionChainSnapshot:
    values = {**snapshot.__dict__, **changes}
    identity_material = json.dumps(
        {
            "ticker": values["ticker"],
            "provider": values["provider"],
            "source_url": values["source_url"],
            "fetched_at": values["fetched_at"],
            "market_at": values["market_at"],
            "available_at": values["available_at"],
            "payload_sha256": values["payload_sha256"],
        },
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: item.isoformat() if isinstance(item, datetime) else str(item),
    )
    values["snapshot_id"] = f"ocs_{hashlib.sha256(identity_material.encode()).hexdigest()}"
    return OptionChainSnapshot(**values)


def test_prefers_safe_long_call_and_binds_exact_snapshot() -> None:
    snapshot = _snapshot(_contract("100", "1.90", "2.00"))

    result = decide_instrument(
        _candidate(target="115"),
        decision_at=DECISION_AT,
        account_equity=Decimal("10000"),
        chain_snapshot=snapshot,
    )

    assert result.expression == "long_call"
    assert result.chain_snapshot_id == snapshot.snapshot_id
    assert result.option_contracts == 2
    assert result.max_loss <= Decimal("500")
    assert result.long_leg["symbol"] == "XYZ261002C00100000"
    assert result.paper_only is True
    assert result.no_live_execution is True
    assert result.broker_order_submitted is False


def test_prefers_highest_ranked_affordable_call_debit_spread() -> None:
    snapshot = _snapshot(
        _contract("100", "7.80", "8.20"),
        _contract("105", "5.20", "5.50"),
        _contract("110", "3.20", "3.45"),
    )

    result = decide_instrument(
        _candidate(),
        decision_at=DECISION_AT,
        account_equity=Decimal("10000"),
        chain_snapshot=snapshot,
    )

    assert result.expression == "call_debit_spread"
    assert result.short_leg is not None
    assert result.max_loss <= Decimal("500")


@pytest.mark.parametrize(
    ("snapshot_factory", "expected_reason"),
    [
        (lambda: None, "option_chain_unavailable"),
        (
            lambda: _copy_snapshot(
                _snapshot(_contract("100", "1.90", "2.00")),
                available_at=DECISION_AT - timedelta(minutes=31),
            ),
            "option_chain_stale",
        ),
        (
            lambda: OptionChainSnapshot(
                **{
                    **_snapshot(_contract("100", "1.90", "2.00")).__dict__,
                    "ticker": "ABC",
                }
            ),
            "option_chain_ticker_mismatch",
        ),
    ],
)
def test_unavailable_stale_or_mismatched_chain_falls_back_without_fabricating_option(
    snapshot_factory, expected_reason
) -> None:
    result = decide_instrument(
        _candidate(),
        decision_at=DECISION_AT,
        account_equity=Decimal("10000"),
        chain_snapshot=snapshot_factory(),
    )

    assert result.expression == "underlying_stock_fallback"
    assert result.fallback_reasons == (expected_reason,)
    assert result.chain_snapshot_id is None
    assert result.long_leg is None and result.short_leg is None
    assert result.max_loss == Decimal("500")
    assert result.underlying_quantity == Decimal("100")


def test_changed_snapshot_identity_falls_back_as_provenance_mismatch() -> None:
    valid = _snapshot(_contract("100", "1.90", "2.00"))
    changed = OptionChainSnapshot(**{**valid.__dict__, "snapshot_id": "ocs_tampered"})

    result = decide_instrument(
        _candidate(),
        decision_at=DECISION_AT,
        account_equity=Decimal("10000"),
        chain_snapshot=changed,
    )

    assert result.expression == "underlying_stock_fallback"
    assert result.fallback_reasons == ("option_chain_provenance_mismatch",)
    assert result.chain_snapshot_id is None


def test_unaffordable_one_contract_falls_back_with_full_stock_risk_sizing() -> None:
    snapshot = _snapshot(_contract("100", "7.90", "8.10"))

    result = decide_instrument(
        _candidate(target="115"),
        decision_at=DECISION_AT,
        account_equity=Decimal("10000"),
        chain_snapshot=snapshot,
    )

    assert result.expression == "underlying_stock_fallback"
    assert result.fallback_reasons == ("option_max_loss_exceeds_budget",)
    assert result.max_loss == Decimal("500")
    assert result.underlying_quantity == Decimal("100")


@pytest.mark.parametrize(
    ("contracts", "target", "expected_reason"),
    [
        ((_contract("100", "1.00", "2.00"),), "110", "option_spread_too_wide"),
        (
            (_contract("100", "1.90", "2.00", oi=0, volume=0),),
            "110",
            "option_liquidity_insufficient",
        ),
        ((_contract("100", "9.90", "10.00"),), "105", "option_target_below_break_even"),
    ],
)
def test_unsafe_option_conditions_preserve_underlying_candidate(
    contracts, target, expected_reason
) -> None:
    result = decide_instrument(
        _candidate(target=target),
        decision_at=DECISION_AT,
        account_equity=Decimal("10000"),
        chain_snapshot=_snapshot(*contracts),
    )

    assert result.expression == "underlying_stock_fallback"
    assert result.fallback_reasons == (expected_reason,)
    assert result.max_loss == Decimal("500")


def test_malformed_snapshot_chain_fails_to_stock_without_propagating_or_fabricating() -> None:
    valid = _snapshot(_contract("100", "1.90", "2.00"))
    malformed = OptionChainSnapshot(
        **{
            **valid.__dict__,
            "contracts": ({**dict(valid.contracts[0]), "bid": "NaN"},),
        }
    )

    result = decide_instrument(
        _candidate(),
        decision_at=DECISION_AT,
        account_equity=Decimal("10000"),
        chain_snapshot=malformed,
    )

    assert result.expression == "underlying_stock_fallback"
    assert result.fallback_reasons == ("option_chain_malformed",)


def test_deterministic_tie_uses_selector_symbol_order() -> None:
    valid = _snapshot(_contract("100", "1.90", "2.00"))
    first = {**dict(valid.contracts[0]), "symbol": "XYZ-TIE-B"}
    second = {**dict(valid.contracts[0]), "symbol": "XYZ-TIE-A"}
    contracts = (first, second)
    payload_hash = hashlib.sha256(
        json.dumps(contracts, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    snapshot = _copy_snapshot(
        valid, contracts=contracts, payload_sha256=payload_hash
    )

    outcomes = [
        decide_instrument(
            _candidate(target="115"),
            decision_at=DECISION_AT,
            account_equity=Decimal("10000"),
            chain_snapshot=snapshot,
        )
        for _ in range(2)
    ]
    assert outcomes[0] == outcomes[1]
    assert outcomes[0].long_leg["symbol"] == "XYZ-TIE-A"


@pytest.mark.parametrize(
    ("decision_at", "equity"),
    [
        (datetime(2026, 9, 17, 20, 5), Decimal("10000")),
        (DECISION_AT, Decimal("NaN")),
        (DECISION_AT, Decimal("0")),
    ],
)
def test_invalid_decision_inputs_fail_closed(decision_at, equity) -> None:
    with pytest.raises(InstrumentDecisionError):
        decide_instrument(
            _candidate(),
            decision_at=decision_at,
            account_equity=equity,
            chain_snapshot=None,
        )
