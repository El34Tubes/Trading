"""Fresh exact read-only option-chain acquisition and provenance.

This boundary has no broker-write operations.  It validates the complete chain
before a selector can consume it and creates a deterministic immutable identity
for the exact normalized payload.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from types import MappingProxyType
from typing import Any

from options_structure_selector import (
    strict_aware_datetime,
    strict_bounded_nonnegative_integer,
    strict_finite_decimal,
    strict_mapping,
    strict_mapping_sequence,
)

READ_ONLY_OPERATIONS = frozenset({"fetch_chain"})
_OCC = re.compile(r"^(?P<underlying>.+?)(?P<expiry>\d{6})(?P<kind>[CP])(?P<strike>\d{8})$")
_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")


class OptionChainProviderUnavailable(RuntimeError):
    """A read-only source could not return a payload."""


@dataclass(frozen=True)
class OptionChainSnapshot:
    snapshot_id: str
    ticker: str
    provider: str
    source_url: str
    fetched_at: datetime
    market_at: datetime
    available_at: datetime
    payload_sha256: str
    contracts: tuple[Mapping[str, Any], ...]
    paper_only: bool = True
    no_live_execution: bool = True
    broker_order_submitted: bool = False

    def chain(self) -> list[dict[str, Any]]:
        """Return a JSON/persistence-safe copy of the exact normalized chain."""
        return [dict(contract) for contract in self.contracts]


@dataclass(frozen=True)
class ReadOnlyChainSource:
    name: str
    priority: int
    fetch_chain: Callable[[str], Mapping[str, Any]]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("source name is required")
        if not callable(self.fetch_chain):
            raise ValueError("fetch_chain must be callable")


def _ticker(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _TICKER.fullmatch(value.strip().upper()):
        raise ValueError(f"{field} must be a canonical ticker")
    return value.strip().upper()


def _canonical_json(value: Any) -> str:
    def default(item: Any) -> str:
        if isinstance(item, datetime):
            return item.isoformat()
        return str(item)

    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=default)


def _occ_parts(symbol: Any) -> tuple[str, str, str]:
    if not isinstance(symbol, str):
        raise ValueError("contract symbol is required")
    compact = symbol.replace(" ", "").upper()
    match = _OCC.fullmatch(compact)
    if match is None:
        raise ValueError(f"invalid OCC contract symbol: {symbol}")
    try:
        datetime.strptime(match.group("expiry"), "%y%m%d")
    except ValueError as exc:
        raise ValueError("invalid OCC expiration") from exc
    option_type = "call" if match.group("kind") == "C" else "put"
    return _ticker(match.group("underlying"), field="OCC underlying"), match.group("expiry"), option_type


def _normalize_contract(
    raw: Mapping[str, Any],
    *,
    ticker: str,
    signal_dt: date,
    decision_at: datetime,
    max_quote_age_minutes: int,
) -> dict[str, Any]:
    contract = dict(strict_mapping(raw, field="contract"))
    occ_underlying, occ_expiration, occ_type = _occ_parts(contract.get("symbol"))
    if occ_underlying != ticker:
        raise ValueError("OCC underlying mismatch")
    try:
        expiration = date.fromisoformat(str(contract["expiration"]))
    except (KeyError, ValueError) as exc:
        raise ValueError("contract expiration is required and must be ISO format") from exc
    if expiration.strftime("%y%m%d") != occ_expiration:
        raise ValueError("contract expiration does not match OCC symbol")
    if str(contract.get("option_type") or "").lower() != occ_type:
        raise ValueError("contract option_type does not match OCC symbol")

    quote_at = strict_aware_datetime(contract.get("quote_at"), field="quote_at").astimezone(
        timezone.utc
    )
    decision_utc = decision_at.astimezone(timezone.utc)
    if quote_at > decision_utc:
        raise ValueError("option quote is after decision time")
    if (decision_utc - quote_at).total_seconds() > max_quote_age_minutes * 60:
        raise ValueError("option quote is stale")
    if str(contract.get("market_date") or "") != signal_dt.isoformat():
        raise ValueError("option quote market date does not match signal date")

    for field in ("strike", "bid", "ask"):
        strict_finite_decimal(contract.get(field), field=field)
    for field in ("bid_size", "ask_size", "volume", "open_interest", "multiplier"):
        contract[field] = strict_bounded_nonnegative_integer(contract.get(field), field=field)
    if contract["multiplier"] != 100 or contract.get("standard_contract") is not True:
        raise ValueError("only standard 100-share option contracts are accepted")

    contract["symbol"] = str(contract["symbol"]).replace(" ", "").upper()
    contract["quote_at"] = quote_at.isoformat()
    contract["market_date"] = signal_dt.isoformat()
    return contract


def normalize_option_chain_snapshot(
    payload: Mapping[str, Any],
    *,
    requested_ticker: str,
    signal_dt: date,
    decision_at: datetime,
    max_quote_age_minutes: int = 30,
) -> OptionChainSnapshot:
    """Validate one complete exact-ticker payload and assign stable provenance."""
    raw = strict_mapping(payload, field="option chain payload")
    requested = _ticker(requested_ticker, field="requested_ticker")
    actual = _ticker(raw.get("ticker"), field="payload ticker")
    if actual != requested:
        raise ValueError("option chain ticker mismatch")
    decision = strict_aware_datetime(decision_at, field="decision_at")
    fetched = strict_aware_datetime(raw.get("fetched_at"), field="fetched_at")
    available = strict_aware_datetime(
        raw.get("available_at", fetched), field="available_at"
    )
    market = strict_aware_datetime(raw.get("market_at", fetched), field="market_at")
    if market > fetched or fetched > available:
        raise ValueError("snapshot times must satisfy market_at <= fetched_at <= available_at")
    if available > decision:
        raise ValueError("available_at must not be after decision_at")
    if max_quote_age_minutes <= 0:
        raise ValueError("max_quote_age_minutes must be positive")

    rows = strict_mapping_sequence(raw.get("contracts"), field="contracts")
    if not rows:
        raise ValueError("contracts must not be empty")
    contracts = tuple(
        sorted(
            (
                _normalize_contract(
                    row,
                    ticker=requested,
                    signal_dt=signal_dt,
                    decision_at=decision,
                    max_quote_age_minutes=max_quote_age_minutes,
                )
                for row in rows
            ),
            key=lambda row: str(row["symbol"]),
        )
    )
    symbols = [str(contract["symbol"]) for contract in contracts]
    if len(symbols) != len(set(symbols)):
        raise ValueError("duplicate option contract symbol")

    provider = str(raw.get("source") or "").strip()
    source_url = str(raw.get("source_url") or "").strip()
    if not provider or not source_url:
        raise ValueError("provider and source_url are required")
    payload_material = _canonical_json(contracts)
    payload_sha256 = hashlib.sha256(payload_material.encode("utf-8")).hexdigest()
    identity_material = _canonical_json(
        {
            "ticker": requested,
            "provider": provider,
            "source_url": source_url,
            "fetched_at": fetched,
            "market_at": market,
            "available_at": available,
            "payload_sha256": payload_sha256,
        }
    )
    snapshot_id = f"ocs_{hashlib.sha256(identity_material.encode('utf-8')).hexdigest()}"
    immutable_contracts = tuple(MappingProxyType(dict(contract)) for contract in contracts)
    return OptionChainSnapshot(
        snapshot_id=snapshot_id,
        ticker=requested,
        provider=provider,
        source_url=source_url,
        fetched_at=fetched,
        market_at=market,
        available_at=available,
        payload_sha256=payload_sha256,
        contracts=immutable_contracts,
    )


def cboe_delayed_source() -> ReadOnlyChainSource:
    """Construct the default public delayed, read-only chain source."""
    from cboe_delayed_options import fetch_cboe_delayed_chain

    def fetch(ticker: str) -> Mapping[str, Any]:
        try:
            return fetch_cboe_delayed_chain(ticker)
        except (OSError, TimeoutError) as exc:
            raise OptionChainProviderUnavailable(str(exc)) from exc

    return ReadOnlyChainSource("cboe_public_delayed_options", 10, fetch)


def acquire_option_chain_snapshot(
    ticker: str,
    *,
    signal_dt: date,
    decision_at: datetime,
    sources: Sequence[ReadOnlyChainSource] | None = None,
    max_quote_age_minutes: int = 30,
) -> OptionChainSnapshot:
    """Acquire by explicit priority; malformed responses fail closed."""
    symbol = _ticker(ticker, field="ticker")
    ordered = sorted(sources or (cboe_delayed_source(),), key=lambda source: source.priority)
    if not ordered:
        raise OptionChainProviderUnavailable("no read-only option-chain source configured")
    failures: list[str] = []
    for source in ordered:
        try:
            payload = source.fetch_chain(symbol)
        except OptionChainProviderUnavailable as exc:
            failures.append(f"{source.name}:{exc}")
            continue
        return normalize_option_chain_snapshot(
            payload,
            requested_ticker=symbol,
            signal_dt=signal_dt,
            decision_at=decision_at,
            max_quote_age_minutes=max_quote_age_minutes,
        )
    raise OptionChainProviderUnavailable("; ".join(failures) or "all providers unavailable")
