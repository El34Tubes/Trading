"""Deterministic bullish option-structure comparison for forward paper research.

The selector has no broker-write capability. It compares normalized call contracts
using conservative quote-side fills and returns a fully auditable decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping, Sequence


D = Decimal


@dataclass(frozen=True)
class SelectorPolicy:
    min_dte: int = 7
    max_dte: int = 35
    min_open_interest: int = 25
    min_volume: int = 10
    max_relative_spread: Decimal = D("0.25")
    max_quote_age_minutes: int = 30
    fill_spread_fraction: Decimal = D("0.75")
    decision_time: datetime | None = None


def _d(value: Any) -> Decimal:
    return D(str(value))


def _q(value: Decimal) -> Decimal:
    return value.quantize(D("0.0001"), rounding=ROUND_HALF_UP)


def _iso_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _leg(contract: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "symbol": str(contract["symbol"]),
        "expiration": str(contract["expiration"]),
        "strike": str(_d(contract["strike"])),
        "bid": str(_d(contract["bid"])),
        "ask": str(_d(contract["ask"])),
        "open_interest": int(contract.get("open_interest") or 0),
        "volume": int(contract.get("volume") or 0),
        "implied_volatility": None if contract.get("implied_volatility") is None else str(_d(contract["implied_volatility"])),
        "quote_at": str(contract.get("quote_at")),
        "multiplier": int(contract.get("multiplier") or 100),
    }


def _screen_contract(contract: Mapping[str, Any], *, as_of: date, policy: SelectorPolicy) -> tuple[list[str], dict[str, Any] | None]:
    reasons: list[str] = []
    try:
        expiration = date.fromisoformat(str(contract["expiration"]))
        strike, bid, ask = (_d(contract[key]) for key in ("strike", "bid", "ask"))
    except (KeyError, ValueError, TypeError):
        return ["invalid_contract_fields"], None
    dte = (expiration - as_of).days
    if not policy.min_dte <= dte <= policy.max_dte:
        reasons.append(f"dte_outside_{policy.min_dte}_{policy.max_dte}")
    if str(contract.get("option_type", "")).lower() != "call":
        reasons.append("not_call")
    if contract.get("standard_contract") is not True or int(contract.get("multiplier") or 0) != 100:
        reasons.append("nonstandard_contract")
    if strike <= 0 or bid <= 0 or ask <= 0 or ask < bid:
        reasons.append("invalid_or_crossed_quote")
    midpoint = (bid + ask) / 2 if ask >= bid else D("0")
    relative_spread = (ask - bid) / midpoint if midpoint > 0 else D("999")
    if relative_spread > policy.max_relative_spread:
        reasons.append("wide_bid_ask_spread")
    if int(contract.get("open_interest") or 0) < policy.min_open_interest and int(contract.get("volume") or 0) < policy.min_volume:
        reasons.append("insufficient_open_interest_and_volume")
    quote_at = _iso_dt(contract.get("quote_at"))
    if quote_at is None:
        reasons.append("missing_quote_timestamp")
    else:
        market_date_value = contract.get("market_date")
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
) -> dict[str, Any]:
    """Compare long calls and same-expiration call debit spreads.

    Ranking maximizes conservative return on defined risk at the technical target,
    after quote-width and time-value penalties. It never forces a selection.
    """
    policy = policy or SelectorPolicy()
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
    for long in eligible:
        # Without a trustworthy delta, keep the long leg ATM or modestly ITM;
        # do not let target-state leverage choose an OTM lottery-ticket long.
        if long["strike"] > underlying_price or long["strike"] < underlying_price * D("0.90"):
            continue
        debit = long["buy_fill"]
        target_value = max(technical_target - long["strike"], D("0"))
        target_profit = target_value - debit
        if target_profit > 0 and long["strike"] <= underlying_price:
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
    selected = candidates[0] if candidates else None
    return {
        "ticker": ticker.upper(), "as_of": as_of.isoformat(),
        "status": "selected" if selected else "no_tradable_option_structure",
        "selected": selected, "evaluated_candidates": candidates,
        "rejected_contracts": rejected,
        "policy": {
            "min_dte": policy.min_dte, "max_dte": policy.max_dte,
            "max_relative_spread": str(policy.max_relative_spread),
            "min_open_interest": policy.min_open_interest, "min_volume": policy.min_volume,
            "fill_model": f"buy_at_{policy.fill_spread_fraction}_through_spread_sell_at_{D('1') - policy.fill_spread_fraction}",
            "structures": ["long_call", "call_debit_spread"],
        },
        "paper_only": True, "no_live_execution": True, "broker_order_submitted": False,
    }
