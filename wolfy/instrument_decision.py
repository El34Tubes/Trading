"""Deterministic option-preferred decisions for allocated paper candidates.

This pure boundary has no persistence or broker capability. A qualified stock
candidate is never discarded merely because its exact option chain is absent or
unsafe; it instead receives explicit stop-defined underlying sizing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
import hashlib
import json
from typing import Any, Literal, Mapping
import uuid

from option_chain_provider import OptionChainSnapshot
from options_structure_selector import SelectorPolicy, select_bullish_option_structure
from orchestration_config import MID_SMALL_PIVOT_POLICY
from portfolio_allocator import PortfolioCandidate


Expression = Literal["long_call", "call_debit_spread", "underlying_stock_fallback"]
RISK_FRACTION = Decimal(str(MID_SMALL_PIVOT_POLICY.risk_fraction_per_position))
MAX_CHAIN_AGE_SECONDS = 30 * 60
SELECTOR_VERSION = "mid_small_exact_option_v1"


class InstrumentDecisionError(ValueError):
    """Input cannot safely produce even an underlying fallback decision."""


def _positive_decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise InstrumentDecisionError(f"{field} must be a finite positive decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise InstrumentDecisionError(f"{field} must be a finite positive decimal") from exc
    if not result.is_finite() or result <= 0:
        raise InstrumentDecisionError(f"{field} must be a finite positive decimal")
    return result


def _aware(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise InstrumentDecisionError(f"{field} must be timezone-aware")
    return value


def _payload_hash(contracts: object) -> str:
    try:
        material = json.dumps(
            contracts,
            sort_keys=True,
            separators=(",", ":"),
            default=lambda item: item.isoformat() if isinstance(item, datetime) else str(item),
        )
    except (TypeError, ValueError) as exc:
        raise InstrumentDecisionError("option chain payload is not canonical JSON") from exc
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _snapshot_identity(snapshot: OptionChainSnapshot) -> str:
    material = json.dumps(
        {
            "ticker": snapshot.ticker,
            "provider": snapshot.provider,
            "source_url": snapshot.source_url,
            "fetched_at": snapshot.fetched_at,
            "market_at": snapshot.market_at,
            "available_at": snapshot.available_at,
            "payload_sha256": snapshot.payload_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: item.isoformat() if isinstance(item, datetime) else str(item),
    )
    return f"ocs_{hashlib.sha256(material.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True, slots=True)
class InstrumentDecision:
    candidate_id: uuid.UUID
    ticker: str
    decision_at: datetime
    chain_snapshot_id: str | None
    selector_version: str
    expression: Expression
    max_loss: Decimal
    risk_budget: Decimal
    option_contracts: int
    underlying_quantity: Decimal | None
    long_leg: Mapping[str, Any] | None
    short_leg: Mapping[str, Any] | None
    fallback_reasons: tuple[str, ...]
    paper_only: bool = True
    no_live_execution: bool = True
    broker_order_submitted: bool = False


def _fallback(
    candidate: PortfolioCandidate,
    *,
    decision_at: datetime,
    risk_budget: Decimal,
    reasons: tuple[str, ...],
    snapshot_id: str | None = None,
) -> InstrumentDecision:
    quantity = risk_budget / (candidate.entry - candidate.stop)
    return InstrumentDecision(
        candidate_id=candidate.candidate_id,
        ticker=candidate.ticker,
        decision_at=decision_at,
        chain_snapshot_id=snapshot_id,
        selector_version=SELECTOR_VERSION,
        expression="underlying_stock_fallback",
        max_loss=risk_budget,
        risk_budget=risk_budget,
        option_contracts=0,
        underlying_quantity=quantity,
        long_leg=None,
        short_leg=None,
        fallback_reasons=reasons,
    )


def _snapshot_rejection(
    snapshot: OptionChainSnapshot,
    *,
    ticker: str,
    decision_at: datetime,
) -> str | None:
    if snapshot.ticker != ticker:
        return "option_chain_ticker_mismatch"
    if (
        not snapshot.provider
        or not snapshot.source_url
        or snapshot.snapshot_id != _snapshot_identity(snapshot)
    ):
        return "option_chain_provenance_mismatch"
    timestamps = (snapshot.market_at, snapshot.fetched_at, snapshot.available_at)
    if any(
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
        for value in timestamps
    ):
        return "option_chain_malformed"
    decision_utc = decision_at.astimezone(timezone.utc)
    available_utc = snapshot.available_at.astimezone(timezone.utc)
    if available_utc > decision_utc:
        return "option_chain_available_after_decision"
    if (decision_utc - available_utc).total_seconds() > MAX_CHAIN_AGE_SECONDS:
        return "option_chain_stale"
    contracts = [dict(contract) for contract in snapshot.contracts]
    if not contracts or _payload_hash(contracts) != snapshot.payload_sha256:
        return "option_chain_malformed"
    try:
        market_dates = {
            date.fromisoformat(str(contract["market_date"])) for contract in contracts
        }
    except (KeyError, ValueError, TypeError):
        return "option_chain_malformed"
    if len(market_dates) != 1:
        return "option_chain_malformed"
    return None


def _fallback_reason(selection: Mapping[str, Any]) -> str:
    if selection.get("unaffordable_candidates") and selection.get("evaluated_candidates"):
        return "option_max_loss_exceeds_budget"
    rejected = selection.get("rejected_contracts") or []
    reasons = {
        reason
        for row in rejected
        if isinstance(row, Mapping)
        for reason in row.get("reasons", ())
    }
    if "invalid_contract_fields" in reasons or "missing_quote_timestamp" in reasons:
        return "option_chain_malformed"
    if "wide_bid_ask_spread" in reasons:
        return "option_spread_too_wide"
    if "insufficient_open_interest_and_volume" in reasons:
        return "option_liquidity_insufficient"
    if not rejected and not selection.get("rejected_long_legs"):
        return "option_target_below_break_even"
    return "no_safe_option_structure"


def decide_instrument(
    candidate: PortfolioCandidate,
    *,
    decision_at: datetime,
    account_equity: Decimal,
    chain_snapshot: OptionChainSnapshot | None,
) -> InstrumentDecision:
    """Prefer one exact bounded-loss option, otherwise size the qualified stock."""
    if not isinstance(candidate, PortfolioCandidate):
        raise InstrumentDecisionError("candidate must satisfy PortfolioCandidate")
    decision = _aware(decision_at, "decision_at")
    equity = _positive_decimal(account_equity, "account_equity")
    risk_budget = equity * RISK_FRACTION
    if chain_snapshot is None:
        return _fallback(
            candidate,
            decision_at=decision,
            risk_budget=risk_budget,
            reasons=("option_chain_unavailable",),
        )
    if not isinstance(chain_snapshot, OptionChainSnapshot):
        return _fallback(
            candidate,
            decision_at=decision,
            risk_budget=risk_budget,
            reasons=("option_chain_malformed",),
        )
    rejection = _snapshot_rejection(
        chain_snapshot, ticker=candidate.ticker, decision_at=decision
    )
    if rejection is not None:
        return _fallback(
            candidate,
            decision_at=decision,
            risk_budget=risk_budget,
            reasons=(rejection,),
        )

    try:
        signal_dt = date.fromisoformat(str(chain_snapshot.contracts[0]["market_date"]))
        selection = select_bullish_option_structure(
            ticker=candidate.ticker,
            underlying_price=candidate.entry,
            technical_target=candidate.target,
            as_of=signal_dt,
            contracts=chain_snapshot.contracts,
            policy=SelectorPolicy(decision_time=decision),
            max_loss_budget=risk_budget,
        )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return _fallback(
            candidate,
            decision_at=decision,
            risk_budget=risk_budget,
            reasons=("option_chain_malformed",),
            snapshot_id=chain_snapshot.snapshot_id,
        )
    selected = selection.get("selected")
    if not isinstance(selected, Mapping):
        return _fallback(
            candidate,
            decision_at=decision,
            risk_budget=risk_budget,
            reasons=(_fallback_reason(selection),),
            snapshot_id=chain_snapshot.snapshot_id,
        )
    per_contract = _positive_decimal(selected.get("max_loss_per_contract"), "max loss")
    contracts = int((risk_budget / per_contract).to_integral_value(rounding=ROUND_DOWN))
    if contracts < 1:
        return _fallback(
            candidate,
            decision_at=decision,
            risk_budget=risk_budget,
            reasons=("option_max_loss_exceeds_budget",),
            snapshot_id=chain_snapshot.snapshot_id,
        )
    expression = selected.get("structure")
    if expression not in ("long_call", "call_debit_spread"):
        return _fallback(
            candidate,
            decision_at=decision,
            risk_budget=risk_budget,
            reasons=("option_chain_malformed",),
            snapshot_id=chain_snapshot.snapshot_id,
        )
    return InstrumentDecision(
        candidate_id=candidate.candidate_id,
        ticker=candidate.ticker,
        decision_at=decision,
        chain_snapshot_id=chain_snapshot.snapshot_id,
        selector_version=SELECTOR_VERSION,
        expression=expression,
        max_loss=per_contract * contracts,
        risk_budget=risk_budget,
        option_contracts=contracts,
        underlying_quantity=None,
        long_leg=selected.get("long_leg"),
        short_leg=selected.get("short_leg"),
        fallback_reasons=(),
    )
