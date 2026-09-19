"""Minimal approved-breakout, underlying-only pivot vertical slice.

This module is deliberately shadow/test-only until exact option-chain integration
and the reviewed release gate land. It has no broker dependency or live action.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any, Callable, Sequence, cast
import uuid

from instrument_decision import InstrumentDecision, decide_instrument
from option_chain_provider import OptionChainProviderUnavailable
from portfolio_allocator import (
    AllocationResult,
    ExistingPosition,
    PortfolioCandidate,
    allocate_portfolio,
)
from recommendation_writer import (
    UnderlyingFallback,
    write_underlying_fallback_recommendations,
)
from setup_evaluators import (
    APPROVED_BREAKOUT_STRATEGY_ID,
    APPROVED_BREAKOUT_STRATEGY_VERSION,
    TREND_PULLBACK_STRATEGY_ID,
    VCP_STRATEGY_ID,
)


SHADOW_PIPELINE_VERSION = "mid-small-shadow-orchestrator-v1"
SHADOW_STAGE_NAMES = (
    "readiness",
    "universe",
    "features_context",
    "setup_evaluations",
    "candidate_persistence",
    "allocation",
    "finalist_chains",
    "instrument_decisions",
    "serialized_write",
    "outcomes",
    "summary",
)
_ALLOWED_STRATEGIES = frozenset(
    {
        "close_confirmed_breakout",
        "trend_pullback_reclaim",
        "volatility_contraction_breakout",
    }
)
_STRATEGY_SLEEVES = {
    APPROVED_BREAKOUT_STRATEGY_ID: "close_confirmed_breakout",
    TREND_PULLBACK_STRATEGY_ID: "trend_pullback_reclaim",
    VCP_STRATEGY_ID: "volatility_contraction_breakout",
}
_HASH = re.compile(r"[0-9a-f]{64}")


class ShadowPipelineValidationError(ValueError):
    """A shadow request violates the frozen pre-release contract."""


class ShadowPipelineConflict(RuntimeError):
    """A run identity was replayed with different immutable inputs."""


def _positive_decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ShadowPipelineValidationError(f"{field} must be a finite positive decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ShadowPipelineValidationError(
            f"{field} must be a finite positive decimal"
        ) from exc
    if not result.is_finite() or result <= 0:
        raise ShadowPipelineValidationError(f"{field} must be a finite positive decimal")
    return result


@dataclass(frozen=True, slots=True)
class ShadowPipelineRequest:
    """Immutable identity and bounded replay controls for a shadow run."""

    run_id: uuid.UUID
    signal_dt: date
    decision_at: datetime
    universe_snapshot_id: uuid.UUID
    universe_fingerprint: str
    account_equity: Decimal
    strategies: tuple[str, ...]
    tickers: tuple[str, ...] = ()
    dry_run: bool = True
    shadow: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, uuid.UUID):
            raise ShadowPipelineValidationError("run_id must be a UUID")
        if type(self.signal_dt) is not date:
            raise ShadowPipelineValidationError("signal_dt must be a date")
        if (
            not isinstance(self.decision_at, datetime)
            or self.decision_at.tzinfo is None
            or self.decision_at.utcoffset() is None
        ):
            raise ShadowPipelineValidationError("decision_at must be timezone-aware")
        if not isinstance(self.universe_snapshot_id, uuid.UUID):
            raise ShadowPipelineValidationError("universe_snapshot_id must be a UUID")
        if not isinstance(self.universe_fingerprint, str) or not _HASH.fullmatch(
            self.universe_fingerprint
        ):
            raise ShadowPipelineValidationError(
                "universe_fingerprint must be canonical lowercase SHA-256"
            )
        equity = _positive_decimal(self.account_equity, "account_equity")
        if (
            not isinstance(self.strategies, tuple)
            or not self.strategies
            or len(set(self.strategies)) != len(self.strategies)
            or not set(self.strategies).issubset(_ALLOWED_STRATEGIES)
        ):
            raise ShadowPipelineValidationError(
                "strategy selection must contain only the three approved pivot sleeves"
            )
        if not isinstance(self.tickers, tuple) or len(self.tickers) > 20:
            raise ShadowPipelineValidationError("ticker replay accepts at most 20 symbols")
        if any(
            not isinstance(ticker, str)
            or not ticker
            or ticker != ticker.strip().upper()
            for ticker in self.tickers
        ) or len(set(self.tickers)) != len(self.tickers):
            raise ShadowPipelineValidationError(
                "ticker replay must be unique canonical uppercase symbols"
            )
        if not isinstance(self.dry_run, bool) or not isinstance(self.shadow, bool):
            raise ShadowPipelineValidationError("dry_run and shadow must be booleans")
        if not self.shadow:
            raise ShadowPipelineValidationError(
                "shadow mode is mandatory until the Task 22/23 release gates pass"
            )
        object.__setattr__(self, "account_equity", equity)

    @property
    def input_fingerprint(self) -> str:
        material = json.dumps(
            {
                "account_equity": str(self.account_equity),
                "decision_at": self.decision_at.isoformat(),
                "pipeline_version": SHADOW_PIPELINE_VERSION,
                "run_id": str(self.run_id),
                "signal_dt": self.signal_dt.isoformat(),
                "strategies": self.strategies,
                "tickers": self.tickers,
                "universe_fingerprint": self.universe_fingerprint,
                "universe_snapshot_id": str(self.universe_snapshot_id),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ShadowPipelineHooks:
    """Explicit side-effect boundaries used by the full state machine."""

    readiness: Callable[..., object]
    universe: Callable[..., object]
    features: Callable[..., object]
    evaluations: Callable[..., object]
    existing_positions: Callable[..., object]
    acquire_chain: Callable[..., object]
    recommendation_writer: Callable[..., object]
    outcomes: Callable[..., object]
    summary: Callable[..., object]
    candidate_persistence: Callable[..., object] | None = None


@dataclass(frozen=True, slots=True)
class ShadowStageRecord:
    name: str
    output: object


class ShadowStageLedger:
    """Idempotent stage cache for retries within one orchestrator process.

    Durable source records remain in the existing daily-run, universe, candidate,
    chain, recommendation and outcome ledgers. This cache prevents repeated hooks
    after an in-process stage crash and rejects a changed input fingerprint.
    """

    def __init__(self) -> None:
        self._fingerprints: dict[uuid.UUID, str] = {}
        self._records: dict[uuid.UUID, dict[str, ShadowStageRecord]] = {}

    def execute(
        self,
        request: ShadowPipelineRequest,
        stage_name: str,
        operation: Callable[[], object],
    ) -> object:
        fingerprint = request.input_fingerprint
        prior = self._fingerprints.setdefault(request.run_id, fingerprint)
        if prior != fingerprint:
            raise ShadowPipelineConflict(
                "run_id already exists with a conflicting input fingerprint"
            )
        records = self._records.setdefault(request.run_id, {})
        if stage_name in records:
            return records[stage_name].output
        output = operation()
        records[stage_name] = ShadowStageRecord(stage_name, output)
        return output

    def read_back(self, run_id: uuid.UUID, input_fingerprint: str) -> tuple[str, ...]:
        if self._fingerprints.get(run_id) != input_fingerprint:
            raise ShadowPipelineConflict("cannot read back a conflicting input fingerprint")
        completed = self._records.get(run_id, {})
        return tuple(name for name in SHADOW_STAGE_NAMES if name in completed)


@dataclass(frozen=True, slots=True)
class ShadowPipelineResult:
    run_id: uuid.UUID
    input_fingerprint: str
    status: str
    stage_names: tuple[str, ...]
    allocation: AllocationResult | None
    instrument_decisions: tuple[InstrumentDecision, ...]
    recommendations_created: int
    broker_orders_created: int
    external_deliveries: int
    paper_only: bool = True
    no_live_execution: bool = True


def _shadow_result(
    request: ShadowPipelineRequest,
    ledger: ShadowStageLedger,
    *,
    status: str,
    allocation: AllocationResult | None = None,
    decisions: tuple[InstrumentDecision, ...] = (),
) -> ShadowPipelineResult:
    return ShadowPipelineResult(
        run_id=request.run_id,
        input_fingerprint=request.input_fingerprint,
        status=status,
        stage_names=ledger.read_back(request.run_id, request.input_fingerprint),
        allocation=allocation,
        instrument_decisions=decisions,
        recommendations_created=0,
        broker_orders_created=0,
        external_deliveries=0,
    )


def run_shadow_pipeline(
    request: ShadowPipelineRequest,
    hooks: ShadowPipelineHooks,
    *,
    ledger: ShadowStageLedger | None = None,
) -> ShadowPipelineResult:
    """Run the three-sleeve pipeline as an idempotent paper-only shadow.

    Recommendation writes and external delivery are intentionally disabled. The
    release path is deliberately absent until Tasks 22 and 23 authorize it.
    """
    if not isinstance(request, ShadowPipelineRequest):
        raise ShadowPipelineValidationError("request must be a ShadowPipelineRequest")
    if not isinstance(hooks, ShadowPipelineHooks):
        raise ShadowPipelineValidationError("hooks must be ShadowPipelineHooks")
    stage_ledger = ledger or ShadowStageLedger()

    readiness = stage_ledger.execute(
        request, "readiness", lambda: hooks.readiness(request)
    )
    if (
        getattr(readiness, "publishable", False) is not True
        or getattr(readiness, "expected_session", None) != request.signal_dt
        or str(getattr(readiness, "universe_snapshot_id", ""))
        != str(request.universe_snapshot_id)
        or getattr(readiness, "universe_source_fingerprint", None)
        != request.universe_fingerprint
    ):
        return _shadow_result(request, stage_ledger, status="pipeline_incomplete")

    universe = stage_ledger.execute(
        request, "universe", lambda: hooks.universe(request, readiness)
    )
    if not isinstance(universe, dict) or (
        str(universe.get("snapshot_id")) != str(request.universe_snapshot_id)
        or universe.get("fingerprint") != request.universe_fingerprint
    ):
        return _shadow_result(request, stage_ledger, status="pipeline_incomplete")

    features = stage_ledger.execute(
        request, "features_context", lambda: hooks.features(request, universe)
    )
    evaluated = stage_ledger.execute(
        request,
        "setup_evaluations",
        lambda: hooks.evaluations(request, universe, features),
    )
    if not isinstance(evaluated, Sequence) or isinstance(evaluated, (str, bytes)):
        raise ShadowPipelineValidationError("evaluations must return a candidate sequence")
    candidates = tuple(evaluated)
    if any(not isinstance(candidate, PortfolioCandidate) for candidate in candidates):
        raise ShadowPipelineValidationError(
            "evaluations must return only PortfolioCandidate values"
        )
    candidates = tuple(
        candidate
        for candidate in candidates
        if _STRATEGY_SLEEVES.get(candidate.strategy_id) in request.strategies
        and (not request.tickers or candidate.ticker in request.tickers)
    )
    persisted = stage_ledger.execute(
        request,
        "candidate_persistence",
        lambda: (
            hooks.candidate_persistence(request, candidates)
            if hooks.candidate_persistence is not None
            else candidates
        ),
    )
    if not isinstance(persisted, Sequence) or isinstance(persisted, (str, bytes)):
        raise ShadowPipelineValidationError(
            "candidate persistence must return a candidate sequence"
        )
    persisted_candidates = tuple(persisted)
    if any(
        not isinstance(candidate, PortfolioCandidate)
        for candidate in persisted_candidates
    ):
        raise ShadowPipelineValidationError(
            "candidate persistence returned malformed candidates"
        )

    def allocate() -> AllocationResult:
        existing = hooks.existing_positions(request)
        if not isinstance(existing, Sequence) or isinstance(existing, (str, bytes)):
            raise ShadowPipelineValidationError("existing positions must be a sequence")
        if any(not isinstance(position, ExistingPosition) for position in existing):
            raise ShadowPipelineValidationError("existing positions are malformed")
        return allocate_portfolio(
            persisted_candidates, existing_positions=tuple(existing)
        )

    allocation = cast(
        AllocationResult,
        stage_ledger.execute(request, "allocation", allocate),
    )

    def acquire_finalist_chains() -> tuple[tuple[PortfolioCandidate, object | None], ...]:
        chains: list[tuple[PortfolioCandidate, object | None]] = []
        for selected in allocation.selected:
            try:
                chain = hooks.acquire_chain(request, selected.candidate)
            except OptionChainProviderUnavailable:
                chain = None
            except (TypeError, ValueError):
                chain = "malformed_option_chain"
            chains.append((selected.candidate, chain))
        return tuple(chains)

    finalist_chains = cast(
        tuple[tuple[PortfolioCandidate, Any], ...],
        stage_ledger.execute(request, "finalist_chains", acquire_finalist_chains),
    )
    decisions = cast(
        tuple[InstrumentDecision, ...],
        stage_ledger.execute(
            request,
            "instrument_decisions",
            lambda: tuple(
                decide_instrument(
                    candidate,
                    decision_at=request.decision_at,
                    account_equity=request.account_equity,
                    chain_snapshot=chain,
                )
                for candidate, chain in finalist_chains
            ),
        ),
    )

    # The write stage is a durable, explicit no-op in shadow. Do not even call
    # the writer hook, which prevents accidental recommendation or broker paths.
    stage_ledger.execute(
        request,
        "serialized_write",
        lambda: {"disabled": True, "reason": "shadow_release_gate_closed"},
    )
    stage_ledger.execute(
        request,
        "outcomes",
        lambda: hooks.outcomes(request, decisions, True),
    )

    if not persisted_candidates:
        status = "no_candidates"
    elif not allocation.selected:
        status = "allocation_blocked"
    else:
        status = "shadow_complete"
    stage_ledger.execute(
        request,
        "summary",
        lambda: hooks.summary(
            request,
            {
                "status": status,
                "allocation": allocation,
                "instrument_decisions": decisions,
                "paper_only": True,
                "no_live_execution": True,
                "broker_orders_created": 0,
                "external_deliveries": 0,
            },
        ),
    )
    completed = stage_ledger.read_back(request.run_id, request.input_fingerprint)
    if status == "shadow_complete" and completed != SHADOW_STAGE_NAMES:
        raise ShadowPipelineConflict(
            "shadow completion requires read-back of every required stage"
        )
    return _shadow_result(
        request,
        stage_ledger,
        status=status,
        allocation=allocation,
        decisions=decisions,
    )


def _base_result(signal_dt: date) -> dict[str, object]:
    return {
        "signal_dt": signal_dt.isoformat(),
        "paper_only": True,
        "no_live_execution": True,
        "broker_orders_created": 0,
        "recommendations_created": 0,
    }


def run_underlying_pivot_slice(
    conn,
    *,
    signal_dt: date,
    readiness,
    candidates: Sequence[PortfolioCandidate],
    dry_run: bool = True,
) -> dict[str, object]:
    """Rank approved breakout candidates and write explicit stock fallbacks.

    Actual inserts fail closed unless the connection is to ``wolfy_test``. This
    bounded slice cannot publish research-only strategies or touch a broker.
    """
    if type(signal_dt) is not date:
        raise ValueError("signal_dt must be a date")
    result = _base_result(signal_dt)
    incomplete_reasons = list(getattr(readiness, "incomplete_reasons", ()) or ())
    snapshot_text = getattr(readiness, "universe_snapshot_id", None)
    if (
        getattr(readiness, "publishable", False) is not True
        or getattr(readiness, "expected_session", None) != signal_dt
        or not snapshot_text
    ):
        result.update(
            status="pipeline_incomplete",
            incomplete_reasons=incomplete_reasons or ["universe_readiness_incomplete"],
        )
        return result
    try:
        snapshot_id = uuid.UUID(str(snapshot_text))
    except (ValueError, TypeError, AttributeError):
        result.update(status="pipeline_incomplete", incomplete_reasons=["invalid_universe_snapshot_id"])
        return result

    approved = [
        item
        for item in candidates
        if item.strategy_id == APPROVED_BREAKOUT_STRATEGY_ID
        and item.strategy_version == APPROVED_BREAKOUT_STRATEGY_VERSION
    ]
    research_only_blocked = len(candidates) - len(approved)
    if not approved:
        result.update(status="no_candidates", research_only_blocked=research_only_blocked)
        return result
    if any(item.universe_snapshot_id != snapshot_id for item in approved):
        result.update(status="pipeline_incomplete", incomplete_reasons=["candidate_snapshot_mismatch"])
        return result

    allocation = allocate_portfolio(approved)
    if not allocation.selected:
        result.update(
            status="allocation_blocked",
            research_only_blocked=research_only_blocked,
            allocation_blocked=len(allocation.decisions),
        )
        return result
    fallbacks = [
        UnderlyingFallback(
            candidate_id=decision.candidate.candidate_id,
            ticker=decision.candidate.ticker,
            strategy_name=decision.candidate.strategy_id,
            strategy_version=decision.candidate.strategy_version,
            sector=decision.candidate.sector,
            global_rank=decision.global_rank,
            entry=decision.candidate.entry,
            stop=decision.candidate.stop,
            target=decision.candidate.target,
        )
        for decision in allocation.selected
    ]
    write_result = write_underlying_fallback_recommendations(
        conn,
        fallbacks=fallbacks,
        signal_dt=signal_dt,
        dry_run=dry_run,
    )
    status = "shadow_preview" if dry_run else (
        "shadow_recommendations" if write_result.inserted else "no_new_recommendations"
    )
    result.update(
        status=status,
        dry_run=dry_run,
        recommendations_created=write_result.inserted,
        recommendations_ranked=len(write_result.selected),
        allocation_selected=len(allocation.selected),
        allocation_blocked=len(allocation.decisions) - len(allocation.selected),
        writer_blocked=[{"ticker": ticker, "reason": reason} for ticker, reason in write_result.blocked],
        research_only_blocked=research_only_blocked,
        instrument_expression="underlying_stock_fallback",
        instrument_reason="option_engine_not_release_ready",
    )
    return result
