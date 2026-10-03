"""Point-in-time, source-backed security identity and absolute risk gates.

This module intentionally does not infer identity from ticker symbols or company
names.  Callers must supply exact provider fields captured in immutable source
observations.  The legacy :mod:`suspicious_activity` module may supply a risk
veto, but its heuristic output can never establish security eligibility.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

DEFAULT_IDENTITY_MAX_AGE = timedelta(days=7)
_US_EXCHANGES = frozenset({"NASDAQ", "NYSE", "NYSE_AMERICAN", "CBOE"})
_ADR_TYPES = frozenset({"adr", "ads", "depositary_receipt"})
_ETP_TYPES = frozenset({"etf", "etn", "etp", "fund", "closed_end_fund"})
_NON_COMMON_REASONS = {
    "preferred": "preferred_stock",
    "preferred_stock": "preferred_stock",
    "unit": "unit",
    "right": "right",
    "rights": "right",
    "warrant": "warrant",
}
_IDENTITY_FIELDS = (
    "security_type",
    "locale",
    "market",
    "primary_exchange",
    "currency",
    "issuer_country",
    "active",
    "delisted_at",
    "product_type",
    "leveraged",
    "inverse",
    "single_stock_product",
)


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _canonical_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty canonical text")
    return value


def _ticker(value: str) -> str:
    ticker = _canonical_text(value, "ticker")
    if ticker != ticker.upper():
        raise ValueError("ticker must be uppercase")
    return ticker


def _validate_window(effective_from: datetime, effective_to: datetime | None) -> None:
    start = _aware(effective_from, "effective_from")
    if effective_to is not None and _aware(effective_to, "effective_to") <= start:
        raise ValueError("effective_to must be after effective_from")


@dataclass(frozen=True)
class SecurityIdentityObservation:
    observation_id: str
    ticker: str
    provider: str
    source_url: str
    effective_from: datetime
    effective_to: datetime | None
    observed_at: datetime
    available_at: datetime
    security_type: str | None
    locale: str | None
    market: str | None
    primary_exchange: str | None
    currency: str | None
    issuer_country: str | None
    active: bool | None
    delisted_at: datetime | None
    product_type: str | None
    leveraged: bool
    inverse: bool
    single_stock_product: bool

    def __post_init__(self) -> None:
        _canonical_text(self.observation_id, "observation_id")
        _ticker(self.ticker)
        _canonical_text(self.provider, "provider")
        _canonical_text(self.source_url, "source_url")
        _validate_window(self.effective_from, self.effective_to)
        observed = _aware(self.observed_at, "observed_at")
        available = _aware(self.available_at, "available_at")
        if available < observed:
            raise ValueError("available_at must not be before observed_at")
        if self.delisted_at is not None:
            _aware(self.delisted_at, "delisted_at")
        for name in ("leveraged", "inverse", "single_stock_product"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        if self.active is not None and not isinstance(self.active, bool):
            raise ValueError("active must be boolean or null")


@dataclass(frozen=True)
class RiskObservation:
    observation_id: str
    ticker: str
    risk_type: str
    decision: str
    reason_code: str
    source: str
    evidence: Mapping[str, Any]
    effective_from: datetime
    effective_to: datetime | None
    available_at: datetime

    def __post_init__(self) -> None:
        _canonical_text(self.observation_id, "observation_id")
        _ticker(self.ticker)
        if self.risk_type not in {"manipulation", "government_interference"}:
            raise ValueError("unsupported risk_type")
        if self.decision not in {"clear", "veto"}:
            raise ValueError("risk decision must be clear or veto")
        _canonical_text(self.reason_code, "reason_code")
        _canonical_text(self.source, "source")
        if not isinstance(self.evidence, Mapping):
            raise ValueError("evidence must be a mapping")
        _validate_window(self.effective_from, self.effective_to)
        _aware(self.available_at, "available_at")


@dataclass(frozen=True)
class DenylistObservation:
    observation_id: str
    ticker: str
    reason_code: str
    source: str
    effective_from: datetime
    effective_to: datetime | None
    available_at: datetime

    def __post_init__(self) -> None:
        _canonical_text(self.observation_id, "observation_id")
        _ticker(self.ticker)
        _canonical_text(self.reason_code, "reason_code")
        _canonical_text(self.source, "source")
        _validate_window(self.effective_from, self.effective_to)
        _aware(self.available_at, "available_at")


@dataclass(frozen=True)
class SecurityEligibilityDecision:
    ticker: str
    decision_at: datetime
    eligible: bool
    reason_codes: tuple[str, ...]
    identity_observation_ids: tuple[str, ...]
    risk_observation_ids: tuple[str, ...]
    denylist_observation_ids: tuple[str, ...]


def _effective(observation: Any, decision_at: datetime) -> bool:
    return (
        observation.available_at <= decision_at
        and observation.effective_from <= decision_at
        and (observation.effective_to is None or decision_at < observation.effective_to)
    )


def _decision(
    ticker: str,
    decision_at: datetime,
    reasons: Sequence[str],
    identities: Sequence[SecurityIdentityObservation] = (),
    risks: Sequence[RiskObservation] = (),
    denylist: Sequence[DenylistObservation] = (),
) -> SecurityEligibilityDecision:
    reason_codes = tuple(sorted(set(reasons)))
    return SecurityEligibilityDecision(
        ticker=ticker,
        decision_at=decision_at,
        eligible=reason_codes == ("eligible_us_common_stock",),
        reason_codes=reason_codes,
        identity_observation_ids=tuple(sorted(row.observation_id for row in identities)),
        risk_observation_ids=tuple(sorted(row.observation_id for row in risks)),
        denylist_observation_ids=tuple(sorted(row.observation_id for row in denylist)),
    )


def _identity_exclusions(row: SecurityIdentityObservation, decision_at: datetime) -> list[str]:
    if any(getattr(row, field) is None for field in _IDENTITY_FIELDS[:7]):
        return ["unknown_identity"]

    security_type = row.security_type.lower()  # type: ignore[union-attr]
    locale = row.locale.lower()  # type: ignore[union-attr]
    market = row.market.lower()  # type: ignore[union-attr]
    exchange = row.primary_exchange.upper()  # type: ignore[union-attr]
    currency = row.currency.upper()  # type: ignore[union-attr]
    country = row.issuer_country.upper()  # type: ignore[union-attr]
    product_type = row.product_type.lower() if row.product_type is not None else None
    reasons: list[str] = []

    if security_type in _ADR_TYPES:
        reasons.append("adr_or_depositary_receipt")
    elif security_type in _ETP_TYPES or product_type in _ETP_TYPES:
        reasons.append("etf_or_etp")
    elif security_type in _NON_COMMON_REASONS:
        reasons.append(_NON_COMMON_REASONS[security_type])
    elif security_type != "common_stock":
        reasons.append("unknown_identity")

    if country != "US":
        reasons.append("foreign_issuer")
    if locale != "us" or currency != "USD":
        reasons.append("foreign_listing")
    if market == "otc" or exchange.startswith("OTC"):
        reasons.append("otc_security")
    elif market != "stocks" or exchange not in _US_EXCHANGES:
        reasons.append("unknown_identity")
    if row.leveraged or product_type == "leveraged_etf":
        reasons.append("leveraged_product")
    if row.inverse or product_type == "inverse_etf":
        reasons.append("inverse_product")
    if row.single_stock_product or product_type == "single_stock_etf":
        reasons.append("single_stock_product")
    if row.active is False:
        reasons.append("inactive_security")
    if row.delisted_at is not None and row.delisted_at <= decision_at:
        reasons.append("delisted_security")
    return reasons


def evaluate_security_eligibility(
    *,
    ticker: str,
    decision_at: datetime,
    identity_observations: Sequence[SecurityIdentityObservation],
    risk_observations: Sequence[RiskObservation] = (),
    denylist_observations: Sequence[DenylistObservation] = (),
    identity_max_age: timedelta = DEFAULT_IDENTITY_MAX_AGE,
) -> SecurityEligibilityDecision:
    """Evaluate exact observations as they were knowable at ``decision_at``.

    Identity must independently establish a fresh U.S. common stock.  Effective
    risk and denylist observations are absolute vetoes, while clear risk rows do
    not compensate for missing or ambiguous identity.
    """
    canonical_ticker = _ticker(ticker)
    decision_time = _aware(decision_at, "decision_at")
    if not isinstance(identity_max_age, timedelta) or identity_max_age <= timedelta(0):
        raise ValueError("identity_max_age must be a positive timedelta")
    all_observations = (*identity_observations, *risk_observations, *denylist_observations)
    if any(row.ticker != canonical_ticker for row in all_observations):
        raise ValueError("observation ticker mismatch")

    identities = [row for row in identity_observations if _effective(row, decision_time)]
    if not identities:
        if identity_observations and all(row.available_at > decision_time for row in identity_observations):
            return _decision(canonical_ticker, decision_time, ["identity_not_available_at_decision"])
        return _decision(canonical_ticker, decision_time, ["unknown_identity"])

    freshest_available = max(row.available_at for row in identities)
    if decision_time - freshest_available > identity_max_age:
        return _decision(
            canonical_ticker,
            decision_time,
            ["stale_identity_source"],
            identities,
        )

    fresh = [row for row in identities if decision_time - row.available_at <= identity_max_age]
    signatures = {tuple(getattr(row, field) for field in _IDENTITY_FIELDS) for row in fresh}
    if len(signatures) != 1:
        return _decision(canonical_ticker, decision_time, ["conflicting_identity"], fresh)

    active_denylist = [row for row in denylist_observations if _effective(row, decision_time)]
    if active_denylist:
        return _decision(
            canonical_ticker,
            decision_time,
            ["denylisted"],
            fresh,
            denylist=active_denylist,
        )

    active_risks = [
        row
        for row in risk_observations
        if _effective(row, decision_time) and row.decision == "veto"
    ]
    if active_risks:
        reasons = [f"{row.risk_type}_risk_veto" for row in active_risks]
        return _decision(canonical_ticker, decision_time, reasons, fresh, active_risks)

    reasons = _identity_exclusions(fresh[0], decision_time)
    if reasons:
        return _decision(canonical_ticker, decision_time, reasons, fresh)
    return _decision(canonical_ticker, decision_time, ["eligible_us_common_stock"], fresh)
