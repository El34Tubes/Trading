"""Common, fail-closed setup evaluation and allocator-candidate contracts."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from daily_evaluation_ledger import CANONICAL_REASON_CODES

_CANDIDATE_NAMESPACE = uuid.UUID("97823487-9278-492d-83cd-957102c2cb29")
_HASH = re.compile(r"[0-9a-f]{64}")
_ASCII_EDGE = "".join(chr(codepoint) for codepoint in range(33)) + "\x7f"


class SetupContractError(ValueError):
    """Raised before writes when a setup evaluation or candidate is unsafe."""


APPROVED_BREAKOUT_STRATEGY_ID = "liquid_rs_breakout_close_confirm_1r"
APPROVED_BREAKOUT_STRATEGY_VERSION = "approved-2026-08-03"
TREND_PULLBACK_STRATEGY_ID = "mid_small_trend_pullback_reclaim_v1"
TREND_PULLBACK_STRATEGY_VERSION = "research-v1"
VCP_STRATEGY_ID = "mid_small_volatility_contraction_breakout_v1"
VCP_STRATEGY_VERSION = "research-v1"
_PULLBACK_RECLAIM_TRIGGERS = frozenset(
    {"close_above_20dma", "close_above_prior_day_high"}
)


@dataclass(frozen=True, slots=True)
class ApprovedBreakoutFacts:
    """Point-in-time inputs to the immutable approved breakout gate."""

    ticker: str
    sector: str
    evaluated_at: datetime
    universe_eligible: bool
    close: object
    high: object
    prior_five_high: object
    prior_five_low: object
    sma_fast: object
    sma_slow: object
    volume_ratio: object
    atr: object
    ticker_return_20d: object
    spy_return_20d: object
    spy_close: object
    spy_sma_50: object
    source_fingerprint: str
    provenance: Mapping[str, Any]
    benchmark_context: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ApprovedBreakoutResult:
    """Common-contract evaluation plus candidate-ready approved terms."""

    evaluation: "SetupEvaluation"
    entry: Decimal | None
    stop: Decimal | None
    target: Decimal | None
    facts_hash: str


@dataclass(frozen=True, slots=True)
class TrendPullbackFacts:
    """Point-in-time inputs to the research-only pullback/reclaim gate."""

    ticker: str
    sector: str
    decision_at: datetime
    evaluated_at: datetime
    features_available_at: datetime
    universe_eligible: bool
    close: object
    prior_day_high: object
    sma_20: object
    sma_50: object
    sma_50_20_sessions_ago: object
    sma_200: object
    atr_14: object
    pullback_sessions: int
    pullback_low: object
    swing_low: object
    pullback_average_volume: object
    average_volume_20d: object
    reclaim_trigger: str
    event_landmine: bool
    risk_veto: bool
    benchmark_context: Mapping[str, Any]
    source_fingerprint: str
    provenance: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TrendPullbackResult:
    evaluation: "SetupEvaluation"
    entry: Decimal | None
    stop: Decimal | None
    target: Decimal | None
    facts_hash: str


@dataclass(frozen=True, slots=True)
class VolatilityContractionFacts:
    """Point-in-time inputs to the research-only VCP breakout gate."""

    ticker: str
    sector: str
    decision_at: datetime
    evaluated_at: datetime
    features_available_at: datetime
    universe_eligible: bool
    close: object
    prior_consolidation_high: object
    contraction_low: object
    sma_50: object
    sma_200: object
    ticker_return_20d: object
    pre_breakout_contraction_ratio: object
    range_expansion_ratio: object
    close_location_value: object
    volume_percentile: object
    event_landmine: bool
    risk_veto: bool
    benchmark_context: Mapping[str, Any]
    source_fingerprint: str
    provenance: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class VolatilityContractionResult:
    evaluation: "SetupEvaluation"
    underlying_setup_passed: bool
    entry: Decimal | None
    stop: Decimal | None
    target: Decimal | None
    facts_hash: str


def _text(value: object, field: str, *, uppercase: bool = False) -> str:
    if not isinstance(value, str) or not value or value != value.strip(_ASCII_EDGE):
        raise SetupContractError(f"{field} must be non-empty canonical text")
    if uppercase and value != value.upper():
        raise SetupContractError(f"{field} must be uppercase")
    return value


def _uuid(value: object, field: str) -> uuid.UUID:
    if not isinstance(value, uuid.UUID):
        raise SetupContractError(f"{field} must be a UUID")
    return value


def _decimal(value: object, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise SetupContractError(f"{field} must be a finite decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SetupContractError(f"{field} must be a finite decimal") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise SetupContractError(f"{field} must be a finite{' positive' if positive else ''} decimal")
    return result


def _json_mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SetupContractError(f"{field} must be a JSON object")
    result = dict(value)
    if any(not isinstance(key, str) for key in result):
        raise SetupContractError(f"{field} keys must be strings")
    try:
        json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SetupContractError(f"{field} must contain finite JSON values") from exc
    return result


def _score_components(value: object) -> dict[str, Decimal]:
    if not isinstance(value, Mapping) or not value:
        raise SetupContractError("score_components must be a non-empty object")
    normalized: dict[str, Decimal] = {}
    for key, component in value.items():
        canonical_key = _text(key, "score component name")
        normalized[canonical_key] = _decimal(component, f"score component {canonical_key}")
    if len(normalized) != len(value):
        raise SetupContractError("score component names must be unique")
    return dict(sorted(normalized.items()))


def _aware_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise SetupContractError(f"{field} must be timezone-aware")
    return value


def _benchmark_context(value: object, decision_at: datetime) -> dict[str, Any]:
    context = _json_mapping(value, "benchmark_context")
    if set(context) != {"SPY", "IWM", "MDY"}:
        raise SetupContractError("benchmark_context must contain exactly SPY, IWM, and MDY")
    normalized: dict[str, Any] = {}
    for ticker in sorted(context):
        observation = _json_mapping(context[ticker], f"benchmark_context.{ticker}")
        if set(observation) != {"return_20d", "available_at"}:
            raise SetupContractError("benchmark observations require return_20d and available_at")
        benchmark_return = _decimal(observation["return_20d"], f"{ticker} return_20d")
        raw_available_at = observation["available_at"]
        if not isinstance(raw_available_at, str):
            raise SetupContractError(f"{ticker} available_at must be an aware ISO timestamp")
        try:
            available_at = datetime.fromisoformat(raw_available_at)
        except ValueError as exc:
            raise SetupContractError(f"{ticker} available_at must be an aware ISO timestamp") from exc
        _aware_datetime(available_at, f"{ticker} available_at")
        if available_at > decision_at:
            raise SetupContractError(f"{ticker} benchmark context was unavailable at decision time")
        normalized[ticker] = {
            "available_at": available_at.isoformat(),
            "return_20d": format(benchmark_return, "f"),
        }
    return normalized


@dataclass(frozen=True, slots=True)
class SetupEvaluation:
    ticker: str
    strategy_id: str
    strategy_version: str
    sector: str
    passed: bool
    reason_code_version: int
    reason_codes: tuple[str, ...]
    terminal_reason: str
    evaluated_at: datetime
    metrics: Mapping[str, Any]
    gate_facts: Mapping[str, Any]
    source_fingerprint: str
    provenance: Mapping[str, Any]
    score_components: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        _text(self.ticker, "ticker", uppercase=True)
        _text(self.strategy_id, "strategy_id")
        _text(self.strategy_version, "strategy_version")
        _text(self.sector, "sector")
        if type(self.passed) is not bool:
            raise SetupContractError("passed must be boolean")
        allowed = CANONICAL_REASON_CODES.get(self.reason_code_version)
        if allowed is None:
            raise SetupContractError("unknown reason code version")
        if (
            not isinstance(self.reason_codes, tuple)
            or not self.reason_codes
            or self.reason_codes != tuple(sorted(set(self.reason_codes)))
            or not set(self.reason_codes).issubset(allowed)
        ):
            raise SetupContractError("reason_codes must be known, sorted, and unique")
        if self.passed != (self.reason_codes == ("passed",)):
            raise SetupContractError("passed and reason_codes are inconsistent")
        if self.terminal_reason not in self.reason_codes:
            raise SetupContractError("terminal_reason must be recorded")
        if not isinstance(self.evaluated_at, datetime) or self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise SetupContractError("evaluated_at must be timezone-aware")
        object.__setattr__(self, "metrics", _json_mapping(self.metrics, "metrics"))
        object.__setattr__(self, "gate_facts", _json_mapping(self.gate_facts, "gate_facts"))
        if not isinstance(self.source_fingerprint, str) or not _HASH.fullmatch(self.source_fingerprint):
            raise SetupContractError("source_fingerprint must be lowercase SHA-256")
        object.__setattr__(self, "provenance", _json_mapping(self.provenance, "provenance"))
        object.__setattr__(self, "score_components", _score_components(self.score_components))


def evaluate_approved_breakout(facts: ApprovedBreakoutFacts) -> ApprovedBreakoutResult:
    """Adapt the approved close-confirmed breakout without changing its gate.

    IWM and MDY remain recorded context only. Candidate terms are returned only
    for an eligible universe member that passes every immutable approved rule.
    """
    ticker = _text(facts.ticker, "ticker", uppercase=True)
    sector = _text(facts.sector, "sector")
    if type(facts.universe_eligible) is not bool:
        raise SetupContractError("universe_eligible must be boolean")
    if not isinstance(facts.evaluated_at, datetime) or facts.evaluated_at.tzinfo is None or facts.evaluated_at.utcoffset() is None:
        raise SetupContractError("evaluated_at must be timezone-aware")
    provenance = _json_mapping(facts.provenance, "provenance")
    _json_mapping(facts.benchmark_context, "benchmark_context")

    close = _decimal(facts.close, "close", positive=True)
    high = _decimal(facts.high, "high", positive=True)
    prior_high = _decimal(facts.prior_five_high, "prior_five_high", positive=True)
    prior_low = _decimal(facts.prior_five_low, "prior_five_low", positive=True)
    sma_fast = None if facts.sma_fast is None else _decimal(facts.sma_fast, "sma_fast", positive=True)
    sma_slow = None if facts.sma_slow is None else _decimal(facts.sma_slow, "sma_slow", positive=True)
    volume_ratio = _decimal(facts.volume_ratio, "volume_ratio")
    atr = _decimal(facts.atr, "atr", positive=True)
    ticker_return = _decimal(facts.ticker_return_20d, "ticker_return_20d")
    spy_return = _decimal(facts.spy_return_20d, "spy_return_20d")
    spy_close = _decimal(facts.spy_close, "spy_close", positive=True)
    spy_sma = _decimal(facts.spy_sma_50, "spy_sma_50", positive=True)

    rs_excess = ticker_return - spy_return
    stop_risk_pct = (close - prior_low) / close
    within_five_pct = close >= max(high, prior_high) * Decimal("0.95")
    trend_passed = (sma_fast is None or close > sma_fast) and (
        sma_fast is None or sma_slow is None or sma_fast >= sma_slow
    )
    failures = (
        (not facts.universe_eligible, "security_ineligible"),
        (spy_close <= spy_sma, "market_regime_failed"),
        (not trend_passed, "trend_failed"),
        (close <= prior_high, "breakout_not_confirmed"),
        (not (ticker_return > spy_return and rs_excess >= Decimal("0.02")), "relative_strength_failed"),
        (volume_ratio < Decimal("1.2"), "volume_failed"),
        (stop_risk_pct > Decimal("0.05"), "stop_risk_too_wide"),
        (not within_five_pct, "overextended"),
    )
    terminal_reason = next((reason for failed, reason in failures if failed), "passed")
    passed = terminal_reason == "passed"
    metrics = {
        "atr": format(atr, "f"),
        "atr_pct": str(atr / close),
        "prior_5d_high": format(prior_high, "f"),
        "prior_5d_low": format(prior_low, "f"),
        "rs_excess_20d": format(rs_excess, "f"),
        "spy_return_20d": format(spy_return, "f"),
        "stop_risk_pct": str(stop_risk_pct),
        "ticker_return_20d": format(ticker_return, "f"),
        "vol_ratio": format(volume_ratio, "f"),
    }
    gate_facts = {
        "approved_rules": {
            "breakout_lookback_days": 5,
            "market_regime": "SPY_above_50_sma",
            "max_hold_days": 10,
            "max_prior_low_risk_pct": "0.05",
            "min_rs_excess_20d": "0.02",
            "min_vol_ratio": "1.2",
            "stop_rule": "close_below_breakout_level",
            "target_r": "1.0",
        },
        "benchmark_context_only": ("IWM", "MDY"),
        "breakout_confirmed": close > prior_high,
        "market_regime_passed": spy_close > spy_sma,
        "trend_passed": trend_passed,
        "universe_eligible": facts.universe_eligible,
        "within_5pct_recent_high": within_five_pct,
    }
    hash_payload = json.dumps(
        {"gate_facts": gate_facts, "metrics": metrics, "provenance": provenance, "ticker": ticker},
        sort_keys=True,
        separators=(",", ":"),
    )
    facts_hash = hashlib.sha256(hash_payload.encode()).hexdigest()
    evaluation = SetupEvaluation(
        ticker=ticker,
        strategy_id=APPROVED_BREAKOUT_STRATEGY_ID,
        strategy_version=APPROVED_BREAKOUT_STRATEGY_VERSION,
        sector=sector,
        passed=passed,
        reason_code_version=2,
        reason_codes=(terminal_reason,),
        terminal_reason=terminal_reason,
        evaluated_at=facts.evaluated_at,
        metrics=metrics,
        gate_facts=gate_facts,
        source_fingerprint=facts.source_fingerprint,
        provenance=provenance,
        score_components={"relative_strength": rs_excess, "volume_confirmation": volume_ratio},
    )
    if not passed:
        return ApprovedBreakoutResult(evaluation, None, None, None, facts_hash)
    entry = close
    stop = prior_high
    target = entry + (entry - stop)
    return ApprovedBreakoutResult(evaluation, entry, stop, target, facts_hash)


def evaluate_trend_pullback(facts: TrendPullbackFacts) -> TrendPullbackResult:
    """Evaluate the frozen research-only trend pullback/reclaim family."""
    ticker = _text(facts.ticker, "ticker", uppercase=True)
    sector = _text(facts.sector, "sector")
    decision_at = _aware_datetime(facts.decision_at, "decision_at")
    evaluated_at = _aware_datetime(facts.evaluated_at, "evaluated_at")
    features_available_at = _aware_datetime(
        facts.features_available_at, "features_available_at"
    )
    if features_available_at > decision_at:
        raise SetupContractError("features were unavailable at decision time")
    if type(facts.universe_eligible) is not bool:
        raise SetupContractError("universe_eligible must be boolean")
    if type(facts.event_landmine) is not bool or type(facts.risk_veto) is not bool:
        raise SetupContractError("event_landmine and risk_veto must be boolean")
    if type(facts.pullback_sessions) is not int:
        raise SetupContractError("pullback_sessions must be an integer")
    reclaim_trigger = _text(facts.reclaim_trigger, "reclaim_trigger")
    if reclaim_trigger not in _PULLBACK_RECLAIM_TRIGGERS:
        raise SetupContractError("reclaim_trigger is not a predeclared variant")
    provenance = _json_mapping(facts.provenance, "provenance")
    benchmark_context = _benchmark_context(facts.benchmark_context, decision_at)

    close = _decimal(facts.close, "close", positive=True)
    prior_day_high = _decimal(facts.prior_day_high, "prior_day_high", positive=True)
    sma_20 = _decimal(facts.sma_20, "sma_20", positive=True)
    sma_50 = _decimal(facts.sma_50, "sma_50", positive=True)
    prior_sma_50 = _decimal(
        facts.sma_50_20_sessions_ago, "sma_50_20_sessions_ago", positive=True
    )
    sma_200 = _decimal(facts.sma_200, "sma_200", positive=True)
    atr = _decimal(facts.atr_14, "atr_14", positive=True)
    pullback_low = _decimal(facts.pullback_low, "pullback_low", positive=True)
    swing_low = _decimal(facts.swing_low, "swing_low", positive=True)
    pullback_volume = _decimal(
        facts.pullback_average_volume, "pullback_average_volume", positive=True
    )
    average_volume = _decimal(facts.average_volume_20d, "average_volume_20d", positive=True)
    if swing_low > pullback_low:
        raise SetupContractError("swing_low cannot exceed pullback_low")

    trend_stack = close > sma_50 > sma_200 and sma_50 > prior_sma_50
    held_50dma = pullback_low >= sma_50
    near_20dma = abs(pullback_low - sma_20) <= atr
    sessions_in_range = 2 <= facts.pullback_sessions <= 7
    volume_contracted = pullback_volume < average_volume
    reclaim_level = sma_20 if reclaim_trigger == "close_above_20dma" else prior_day_high
    reclaim_confirmed = close > reclaim_level
    stop_risk_pct = (close - swing_low) / close
    stop_valid = swing_low < close and stop_risk_pct <= Decimal("0.08")
    failures = (
        (not facts.universe_eligible or facts.risk_veto, "security_ineligible"),
        (facts.event_landmine, "event_landmine"),
        (not trend_stack or not held_50dma, "trend_failed"),
        (not sessions_in_range or not near_20dma, "pullback_shape_failed"),
        (not volume_contracted, "volume_failed"),
        (not reclaim_confirmed, "reclaim_not_confirmed"),
        (not stop_valid, "stop_risk_too_wide"),
    )
    terminal_reason = next((reason for failed, reason in failures if failed), "passed")
    passed = terminal_reason == "passed"
    metrics = {
        "atr_14": format(atr, "f"),
        "pullback_sessions": facts.pullback_sessions,
        "pullback_volume_ratio": str(pullback_volume / average_volume),
        "stop_risk_pct": str(stop_risk_pct),
        "trend_50dma_rise": str((sma_50 / prior_sma_50) - 1),
    }
    gate_facts = {
        "benchmark_context": benchmark_context,
        "benchmark_context_only": ["IWM", "MDY", "SPY"],
        "event_landmine": facts.event_landmine,
        "governance_status": "research_only",
        "held_50dma": held_50dma,
        "max_stop_risk_pct": "0.08",
        "near_20dma_within_atr": near_20dma,
        "pullback_sessions_in_range": sessions_in_range,
        "reclaim_confirmed": reclaim_confirmed,
        "reclaim_trigger": reclaim_trigger,
        "risk_veto": facts.risk_veto,
        "trend_stack_passed": trend_stack,
        "universe_eligible": facts.universe_eligible,
        "volume_contracted": volume_contracted,
    }
    hash_payload = json.dumps(
        {
            "decision_at": decision_at.isoformat(),
            "gate_facts": gate_facts,
            "metrics": metrics,
            "provenance": provenance,
            "ticker": ticker,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    facts_hash = hashlib.sha256(hash_payload.encode()).hexdigest()
    evaluation = SetupEvaluation(
        ticker=ticker,
        strategy_id=TREND_PULLBACK_STRATEGY_ID,
        strategy_version=TREND_PULLBACK_STRATEGY_VERSION,
        sector=sector,
        passed=passed,
        reason_code_version=2,
        reason_codes=(terminal_reason,),
        terminal_reason=terminal_reason,
        evaluated_at=evaluated_at,
        metrics=metrics,
        gate_facts=gate_facts,
        source_fingerprint=facts.source_fingerprint,
        provenance=provenance,
        score_components={
            "trend_50dma_rise": (sma_50 / prior_sma_50) - 1,
            "volume_contraction": Decimal(1) - (pullback_volume / average_volume),
        },
    )
    if not passed:
        return TrendPullbackResult(evaluation, None, None, None, facts_hash)
    target = close + (close - swing_low) * Decimal(2)
    return TrendPullbackResult(evaluation, close, swing_low, target, facts_hash)


def evaluate_volatility_contraction(
    facts: VolatilityContractionFacts,
) -> VolatilityContractionResult:
    """Evaluate an underlying VCP breakout independently of option availability."""
    ticker = _text(facts.ticker, "ticker", uppercase=True)
    sector = _text(facts.sector, "sector")
    decision_at = _aware_datetime(facts.decision_at, "decision_at")
    evaluated_at = _aware_datetime(facts.evaluated_at, "evaluated_at")
    features_available_at = _aware_datetime(
        facts.features_available_at, "features_available_at"
    )
    if features_available_at > decision_at:
        raise SetupContractError("features were unavailable at decision time")
    if decision_at - features_available_at > timedelta(days=1):
        raise SetupContractError("features are stale at decision time")
    if type(facts.universe_eligible) is not bool:
        raise SetupContractError("universe_eligible must be boolean")
    if type(facts.event_landmine) is not bool or type(facts.risk_veto) is not bool:
        raise SetupContractError("event_landmine and risk_veto must be boolean")
    provenance = _json_mapping(facts.provenance, "provenance")
    benchmark_context = _benchmark_context(facts.benchmark_context, decision_at)

    close = _decimal(facts.close, "close", positive=True)
    prior_high = _decimal(
        facts.prior_consolidation_high, "prior_consolidation_high", positive=True
    )
    contraction_low = _decimal(facts.contraction_low, "contraction_low", positive=True)
    sma_50 = _decimal(facts.sma_50, "sma_50", positive=True)
    sma_200 = _decimal(facts.sma_200, "sma_200", positive=True)
    ticker_return = _decimal(facts.ticker_return_20d, "ticker_return_20d")
    contraction = _decimal(
        facts.pre_breakout_contraction_ratio,
        "pre_breakout_contraction_ratio",
        positive=True,
    )
    expansion = _decimal(
        facts.range_expansion_ratio, "range_expansion_ratio", positive=True
    )
    close_location = _decimal(facts.close_location_value, "close_location_value")
    volume_percentile = _decimal(facts.volume_percentile, "volume_percentile")
    if not Decimal(0) <= close_location <= Decimal(1):
        raise SetupContractError("close_location_value must be between zero and one")
    if not Decimal(0) <= volume_percentile <= Decimal(1):
        raise SetupContractError("volume_percentile must be between zero and one")
    if contraction_low >= close:
        raise SetupContractError("contraction_low must be below close")

    benchmark_returns = tuple(
        Decimal(observation["return_20d"])
        for observation in benchmark_context.values()
    )
    strongest_benchmark_return = max(benchmark_returns)
    trend_confirmed = close > sma_50 > sma_200
    relative_strength_confirmed = ticker_return > strongest_benchmark_return
    contraction_confirmed = contraction <= Decimal("0.75")
    expansion_confirmed = (
        expansion >= Decimal("1.50") and close_location >= Decimal("0.70")
    )
    volume_confirmed = volume_percentile >= Decimal("0.50")
    breakout_confirmed = close > prior_high
    stop_risk_pct = (close - contraction_low) / close
    stop_valid = stop_risk_pct <= Decimal("0.08")
    failures = (
        (not facts.universe_eligible or facts.risk_veto, "security_ineligible"),
        (facts.event_landmine, "event_landmine"),
        (not trend_confirmed, "trend_failed"),
        (not relative_strength_confirmed, "relative_strength_failed"),
        (not contraction_confirmed, "volatility_contraction_failed"),
        (not expansion_confirmed, "range_expansion_failed"),
        (not volume_confirmed, "volume_failed"),
        (not breakout_confirmed, "breakout_not_confirmed"),
        (not stop_valid, "stop_risk_too_wide"),
    )
    terminal_reason = next((reason for failed, reason in failures if failed), "passed")
    passed = terminal_reason == "passed"
    metrics = {
        "close_location_value": format(close_location, "f"),
        "pre_breakout_contraction_ratio": format(contraction, "f"),
        "range_expansion_ratio": format(expansion, "f"),
        "relative_strength_excess": format(
            ticker_return - strongest_benchmark_return, "f"
        ),
        "stop_risk_pct": str(stop_risk_pct),
        "ticker_return_20d": format(ticker_return, "f"),
        "volume_percentile": format(volume_percentile, "f"),
    }
    gate_facts = {
        "benchmark_context": benchmark_context,
        "benchmark_context_only": ["IWM", "MDY", "SPY"],
        "breakout_confirmed": breakout_confirmed,
        "event_landmine": facts.event_landmine,
        "governance_status": "research_only",
        "instrument_selection": "downstream_option_preferred_or_stock_fallback",
        "range_expansion_confirmed": expansion_confirmed,
        "relative_strength_confirmed": relative_strength_confirmed,
        "risk_veto": facts.risk_veto,
        "trend_confirmed": trend_confirmed,
        "underlying_setup_passed": passed,
        "universe_eligible": facts.universe_eligible,
        "volatility_contraction_confirmed": contraction_confirmed,
        "volume_confirmed": volume_confirmed,
    }
    hash_payload = json.dumps(
        {
            "decision_at": decision_at.isoformat(),
            "gate_facts": gate_facts,
            "metrics": metrics,
            "provenance": provenance,
            "ticker": ticker,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    facts_hash = hashlib.sha256(hash_payload.encode()).hexdigest()
    evaluation = SetupEvaluation(
        ticker=ticker,
        strategy_id=VCP_STRATEGY_ID,
        strategy_version=VCP_STRATEGY_VERSION,
        sector=sector,
        passed=passed,
        reason_code_version=2,
        reason_codes=(terminal_reason,),
        terminal_reason=terminal_reason,
        evaluated_at=evaluated_at,
        metrics=metrics,
        gate_facts=gate_facts,
        source_fingerprint=facts.source_fingerprint,
        provenance=provenance,
        score_components={
            "relative_strength": ticker_return - strongest_benchmark_return,
            "range_expansion": expansion,
            "volume_percentile": volume_percentile,
            "volatility_contraction": Decimal(1) - contraction,
        },
    )
    if not passed:
        return VolatilityContractionResult(
            evaluation, False, None, None, None, facts_hash
        )
    target = close + (close - contraction_low) * Decimal(2)
    return VolatilityContractionResult(
        evaluation, True, close, contraction_low, target, facts_hash
    )


@dataclass(frozen=True, slots=True)
class SetupCandidate:
    run_id: uuid.UUID
    universe_snapshot_id: uuid.UUID
    gate_evaluation_id: int
    ticker: str
    strategy_id: str
    strategy_version: str
    sector: str
    score: Decimal
    score_components: Mapping[str, Decimal]
    entry: Decimal
    stop: Decimal
    target: Decimal
    facts_hash: str

    def __post_init__(self) -> None:
        _uuid(self.run_id, "run_id")
        _uuid(self.universe_snapshot_id, "universe_snapshot_id")
        if type(self.gate_evaluation_id) is not int or self.gate_evaluation_id <= 0:
            raise SetupContractError("gate_evaluation_id must be a positive integer")
        _text(self.ticker, "ticker", uppercase=True)
        _text(self.strategy_id, "strategy_id")
        _text(self.strategy_version, "strategy_version")
        _text(self.sector, "sector")
        score = _decimal(self.score, "score")
        components = _score_components(self.score_components)
        entry = _decimal(self.entry, "entry", positive=True)
        stop = _decimal(self.stop, "stop", positive=True)
        target = _decimal(self.target, "target", positive=True)
        if score != sum(components.values(), Decimal(0)):
            raise SetupContractError("score must equal the deterministic score component sum")
        if stop >= entry:
            raise SetupContractError("stop must be below entry")
        if target <= entry:
            raise SetupContractError("target must be above entry")
        if not isinstance(self.facts_hash, str) or not _HASH.fullmatch(self.facts_hash):
            raise SetupContractError("facts_hash must be lowercase SHA-256")
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "score_components", components)
        object.__setattr__(self, "entry", entry)
        object.__setattr__(self, "stop", stop)
        object.__setattr__(self, "target", target)


def _candidate_id(candidate: SetupCandidate) -> uuid.UUID:
    identity = ":".join(
        (
            str(candidate.run_id),
            candidate.ticker,
            candidate.strategy_id,
            candidate.strategy_version,
        )
    )
    return uuid.uuid5(_CANDIDATE_NAMESPACE, identity)


def persist_setup_candidate(conn, candidate: SetupCandidate) -> uuid.UUID:
    """Persist one immutable candidate after relationally checking every binding."""
    from psycopg.types.json import Jsonb

    if conn.execute("SELECT current_database()").fetchone()[0] != "wolfy_test":
        raise RuntimeError("setup candidate writes are disabled outside wolfy_test before release gate")
    binding = conn.execute(
        """SELECT run.universe_snapshot_id, gate.ticker, gate.strategy, gate.passed,
                  member.sector, member.included
             FROM daily_evaluation_runs AS run
             LEFT JOIN setup_gate_evaluations AS gate
               ON gate.id=%s AND gate.run_id=run.id
             LEFT JOIN recommendation_universe_members AS member
               ON member.snapshot_id=%s AND member.ticker=%s
            WHERE run.id=%s""",
        (
            candidate.gate_evaluation_id,
            candidate.universe_snapshot_id,
            candidate.ticker,
            candidate.run_id,
        ),
    ).fetchone()
    if binding is None:
        raise SetupContractError("candidate run does not exist")
    snapshot_id, gate_ticker, gate_strategy, gate_passed, member_sector, included = binding
    if snapshot_id != str(candidate.universe_snapshot_id):
        raise SetupContractError("candidate universe snapshot differs from immutable run")
    if (gate_ticker, gate_strategy) != (candidate.ticker, candidate.strategy_id):
        raise SetupContractError("candidate does not match its terminal gate")
    if gate_passed is not True:
        raise SetupContractError("candidate requires a passed terminal gate")
    if included is not True or member_sector != candidate.sector:
        raise SetupContractError("candidate must match an included universe member and sector")

    candidate_id = _candidate_id(candidate)
    payload = (
        candidate.run_id,
        candidate.universe_snapshot_id,
        candidate.gate_evaluation_id,
        candidate.ticker,
        candidate.strategy_id,
        candidate.strategy_version,
        candidate.sector,
        candidate.score,
        Jsonb({key: format(value, "f") for key, value in candidate.score_components.items()}),
        candidate.entry,
        candidate.stop,
        candidate.target,
        candidate.facts_hash,
    )
    inserted = conn.execute(
        """INSERT INTO setup_candidates(
               candidate_id,run_id,universe_snapshot_id,gate_evaluation_id,ticker,
               strategy_id,strategy_version,sector,score,score_components,
               entry,stop,target,facts_hash)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
             ON CONFLICT (candidate_id) DO NOTHING
             RETURNING candidate_id""",
        (candidate_id, *payload),
    ).fetchone()
    if inserted is not None:
        return inserted[0]
    stored = conn.execute(
        """SELECT run_id,universe_snapshot_id,gate_evaluation_id,ticker,strategy_id,
                  strategy_version,sector,score,score_components,entry,stop,target,facts_hash
             FROM setup_candidates WHERE candidate_id=%s""",
        (candidate_id,),
    ).fetchone()
    expected = (
        *payload[:8],
        {key: format(value, "f") for key, value in candidate.score_components.items()},
        *payload[9:],
    )
    if stored != expected:
        raise SetupContractError("setup candidate identity is immutable and conflicts with rerun")
    return candidate_id
