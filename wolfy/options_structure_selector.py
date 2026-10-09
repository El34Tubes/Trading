"""Deterministic bullish option-structure comparison for forward paper research.

The selector has no broker-write capability. It compares normalized call contracts
using conservative quote-side fills and returns a fully auditable decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo


D = Decimal
MAX_PROVIDER_INTEGER = 2_147_483_647


@dataclass(frozen=True)
class SelectorPolicy:
    min_dte: int = 7
    max_dte: int = 35
    min_open_interest: int = 25
    min_volume: int = 10
    max_relative_spread: Decimal = D("0.25")
    max_quote_age_minutes: int = 30
    fill_spread_fraction: Decimal = D("0.75")
    min_long_moneyness: Decimal = D("0.90")
    max_long_moneyness: Decimal = D("1.00")
    policy_version: str = "strict_options_v1"
    decision_time: datetime | None = None


def aggressive_options_v2_policy(*, decision_time: datetime | None = None) -> SelectorPolicy:
    """Return the separate, looser policy authorized only for aggressive v2 paper research."""
    if decision_time is None or decision_time.tzinfo is None or decision_time.utcoffset() is None:
        raise ValueError("aggressive options v2 requires a timezone-aware decision_time")
    return SelectorPolicy(
        min_dte=7,
        max_dte=28,
        min_open_interest=10,
        min_volume=1,
        max_relative_spread=D("0.35"),
        fill_spread_fraction=D("0.80"),
        min_long_moneyness=D("0.90"),
        max_long_moneyness=D("1.05"),
        policy_version="aggressive_options_v2",
        decision_time=decision_time,
    )


def strict_finite_decimal(value: Any, *, field: str = "value") -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} must be a finite decimal")
    try:
        parsed = D(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be a finite decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be a finite decimal")
    return parsed


def strict_bounded_nonnegative_integer(value: Any, *, field: str = "value") -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a canonical bounded nonnegative integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]*", value):
        parsed = int(value)
    else:
        raise ValueError(f"{field} must be a canonical bounded nonnegative integer")
    if not 0 <= parsed <= MAX_PROVIDER_INTEGER:
        raise ValueError(f"{field} must be a canonical bounded nonnegative integer")
    return parsed


def strict_aware_datetime(value: Any, *, field: str = "timestamp") -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be a timezone-aware datetime") from exc
    else:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    return parsed


def strict_mapping(value: Any, *, field: str = "value") -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a mapping")
    return value


def strict_mapping_sequence(
    value: Any, *, field: str = "value"
) -> Sequence[Mapping[str, Any]]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or not all(isinstance(item, Mapping) for item in value)
    ):
        raise ValueError(f"{field} must be a sequence of mappings")
    return value


def _q(value: Decimal) -> Decimal:
    return value.quantize(D("0.0001"), rounding=ROUND_HALF_UP)


def _iso_dt(value: Any) -> datetime | None:
    try:
        return strict_aware_datetime(value, field="quote_at").astimezone(timezone.utc)
    except ValueError:
        return None


def _leg(contract: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "symbol": str(contract["symbol"]),
        "expiration": str(contract["expiration"]),
        "strike": str(strict_finite_decimal(contract["strike"], field="strike")),
        "bid": str(strict_finite_decimal(contract["bid"], field="bid")),
        "ask": str(strict_finite_decimal(contract["ask"], field="ask")),
        "open_interest": strict_bounded_nonnegative_integer(
            contract.get("open_interest"), field="open_interest"
        ),
        "volume": strict_bounded_nonnegative_integer(contract.get("volume"), field="volume"),
        "implied_volatility": (
            None
            if contract.get("implied_volatility") is None
            else str(
                strict_finite_decimal(
                    contract["implied_volatility"], field="implied_volatility"
                )
            )
        ),
        "quote_at": str(contract.get("quote_at")),
        "multiplier": strict_bounded_nonnegative_integer(
            contract.get("multiplier"), field="multiplier"
        ),
    }


def _screen_contract(contract: Mapping[str, Any], *, as_of: date, policy: SelectorPolicy) -> tuple[list[str], dict[str, Any] | None]:
    reasons: list[str] = []
    aggressive_v2 = policy.policy_version == "aggressive_options_v2"
    try:
        expiration = date.fromisoformat(str(contract["expiration"]))
        strike, bid, ask = (
            strict_finite_decimal(contract[key], field=key)
            for key in ("strike", "bid", "ask")
        )
        open_interest = strict_bounded_nonnegative_integer(
            contract.get("open_interest"), field="open_interest"
        )
        volume = strict_bounded_nonnegative_integer(contract.get("volume"), field="volume")
        multiplier = strict_bounded_nonnegative_integer(
            contract.get("multiplier"), field="multiplier"
        )
        if contract.get("implied_volatility") is not None:
            strict_finite_decimal(
                contract["implied_volatility"], field="implied_volatility"
            )
    except (KeyError, InvalidOperation, ValueError, TypeError):
        return ["invalid_contract_fields"], None
    dte = (expiration - as_of).days
    if not policy.min_dte <= dte <= policy.max_dte:
        reasons.append(f"dte_outside_{policy.min_dte}_{policy.max_dte}")
    if str(contract.get("option_type", "")).lower() != "call":
        reasons.append("not_call")
    if contract.get("standard_contract") is not True or multiplier != 100:
        reasons.append("nonstandard_contract")
    if strike <= 0 or bid <= 0 or ask <= 0 or ask < bid:
        reasons.append("invalid_or_crossed_quote")
    midpoint = (bid + ask) / 2 if ask >= bid else D("0")
    relative_spread = (ask - bid) / midpoint if midpoint > 0 else D("999")
    if relative_spread > policy.max_relative_spread:
        reasons.append("wide_bid_ask_spread")
    if open_interest < policy.min_open_interest and volume < policy.min_volume:
        reasons.append("insufficient_open_interest_and_volume")
    quote_at = _iso_dt(contract.get("quote_at"))
    if quote_at is None:
        reasons.append("missing_quote_timestamp")
    else:
        market_date_value = contract.get("market_date")
        if aggressive_v2:
            derived_market_date = quote_at.astimezone(ZoneInfo("America/New_York")).date().isoformat()
            if market_date_value is not None and str(market_date_value) != derived_market_date:
                reasons.append("market_date_mismatch")
            elif derived_market_date != as_of.isoformat():
                reasons.append("stale_quote")
        else:
            quote_market_date = str(market_date_value) if market_date_value else quote_at.date().isoformat()
            if quote_market_date != as_of.isoformat():
                reasons.append("stale_quote")
        if policy.decision_time is not None:
            decision = policy.decision_time.astimezone(timezone.utc)
            if quote_at > decision:
                reasons.append("quote_after_decision_time")
            elif (decision - quote_at).total_seconds() > policy.max_quote_age_minutes * 60:
                reasons.append("stale_quote")
    normalized = None
    if not reasons:
        buy_fill = bid + (ask - bid) * policy.fill_spread_fraction
        sell_fill = bid + (ask - bid) * (D("1") - policy.fill_spread_fraction)
        normalized = {
            "raw": contract,
            "expiration": expiration,
            "dte": dte,
            "strike": strike,
            "bid": bid,
            "ask": ask,
            "relative_spread": relative_spread,
            "buy_fill": buy_fill,
            "sell_fill": sell_fill,
        }
    return sorted(set(reasons)), normalized


def select_bullish_option_structure(
    *, ticker: str, underlying_price: Decimal, technical_target: Decimal,
    as_of: date, contracts: Sequence[Mapping[str, Any]], policy: SelectorPolicy | None = None,
    max_loss_budget: Decimal | None = None,
) -> dict[str, Any]:
    """Compare long calls and same-expiration call debit spreads.

    Ranking maximizes conservative return on defined risk at the technical target,
    after quote-width and time-value penalties. It never forces a selection.
    """
    policy = policy or SelectorPolicy()
    if policy.decision_time is not None:
        strict_aware_datetime(policy.decision_time, field="decision_time")
    strict_mapping_sequence(contracts, field="contracts")
    budget = None
    if max_loss_budget is not None:
        budget = strict_finite_decimal(max_loss_budget, field="max_loss_budget")
        if budget <= 0:
            raise ValueError("max_loss_budget must be positive")
    if underlying_price <= 0 or technical_target <= underlying_price:
        raise ValueError("bullish target must be above a positive underlying price")
    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for contract in contracts:
        reasons, normalized = _screen_contract(contract, as_of=as_of, policy=policy)
        if reasons:
            rejected.append({"symbol": str(contract.get("symbol") or "unknown"), "reasons": reasons})
        elif normalized is not None:
            eligible.append(normalized)

    candidates: list[dict[str, Any]] = []
    rejected_long_legs: list[dict[str, Any]] = []
    for long in eligible:
        moneyness = long["strike"] / underlying_price
        long_reasons: list[str] = []
        if moneyness < policy.min_long_moneyness:
            long_reasons.append(f"long_moneyness_below_{policy.min_long_moneyness}")
        if moneyness > policy.max_long_moneyness:
            long_reasons.append(f"long_moneyness_above_{policy.max_long_moneyness}")
        if long_reasons:
            rejected_long_legs.append({
                "symbol": str(long["raw"].get("symbol") or "unknown"),
                "reasons": long_reasons,
            })
            continue
        debit = long["buy_fill"]
        target_value = max(technical_target - long["strike"], D("0"))
        target_profit = target_value - debit
        if target_profit > 0:
            score = (target_profit / debit) - long["relative_spread"] * D("0.5")
            candidates.append({
                "structure": "long_call", "defined_risk": True, "dte": long["dte"],
                "expiration": long["expiration"].isoformat(), "long_leg": _leg(long["raw"]),
                "short_leg": None, "conservative_debit": _q(debit),
                "max_loss_per_contract": _q(debit * 100), "max_profit_per_contract": None,
                "target_value": _q(target_value), "target_profit": _q(target_profit), "score": _q(score),
                "selection_facts": ["positive_conservative_profit_at_technical_target", "uncapped_upside"],
            })
        for short in eligible:
            if short["expiration"] != long["expiration"] or short["strike"] <= long["strike"]:
                continue
            width = short["strike"] - long["strike"]
            spread_debit = long["buy_fill"] - short["sell_fill"]
            if spread_debit <= 0 or spread_debit >= width:
                continue
            spread_value = min(max(technical_target - long["strike"], D("0")), width)
            spread_profit = spread_value - spread_debit
            if spread_profit <= 0:
                continue
            target_gap = abs(short["strike"] - technical_target) / underlying_price
            score = (spread_profit / spread_debit) - target_gap - (long["relative_spread"] + short["relative_spread"]) * D("0.25")
            candidates.append({
                "structure": "call_debit_spread", "defined_risk": True, "dte": long["dte"],
                "expiration": long["expiration"].isoformat(), "long_leg": _leg(long["raw"]),
                "short_leg": _leg(short["raw"]), "conservative_debit": _q(spread_debit),
                "max_loss_per_contract": _q(spread_debit * 100),
                "max_profit_per_contract": _q((width - spread_debit) * 100),
                "target_value": _q(spread_value), "target_profit": _q(spread_profit), "score": _q(score),
                "selection_facts": ["positive_conservative_profit_at_technical_target", "same_expiration_defined_risk", "short_strike_target_alignment"],
            })
    candidates.sort(key=lambda row: (-row["score"], row["max_loss_per_contract"], row["dte"], row["structure"], row["long_leg"]["symbol"], (row["short_leg"] or {}).get("symbol", "")))
    unaffordable_candidates = (
        [row for row in candidates if row["max_loss_per_contract"] > budget]
        if budget is not None
        else []
    )
    affordable_candidates = (
        [row for row in candidates if row["max_loss_per_contract"] <= budget]
        if budget is not None
        else candidates
    )
    selected = affordable_candidates[0] if affordable_candidates else None
    return {
        "ticker": ticker.upper(), "as_of": as_of.isoformat(),
        "status": "selected" if selected else "no_tradable_option_structure",
        "selected": selected, "evaluated_candidates": candidates,
        "unaffordable_candidates": unaffordable_candidates,
        "rejected_contracts": rejected,
        "rejected_long_legs": rejected_long_legs,
        "policy": {
            "policy_version": policy.policy_version,
            "min_dte": policy.min_dte, "max_dte": policy.max_dte,
            "max_relative_spread": str(policy.max_relative_spread),
            "min_open_interest": policy.min_open_interest, "min_volume": policy.min_volume,
            "min_long_moneyness": str(policy.min_long_moneyness),
            "max_long_moneyness": str(policy.max_long_moneyness),
            "fill_spread_fraction": str(policy.fill_spread_fraction),
            "fill_model": f"buy_at_{policy.fill_spread_fraction}_through_spread_sell_at_{D('1') - policy.fill_spread_fraction}",
            "structures": ["long_call", "call_debit_spread"],
            "decision_time": policy.decision_time.isoformat() if policy.decision_time is not None else None,
        },
        "input_contracts": [dict(contract) for contract in contracts] if policy.policy_version == "aggressive_options_v2" else None,
        "paper_only": True, "no_live_execution": True, "broker_order_submitted": False,
    }
