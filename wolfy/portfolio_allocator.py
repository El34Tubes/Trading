"""Deterministic global allocator for Wolfy's paper-only pivot candidates."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable, Sequence
import uuid

from orchestration_config import MID_SMALL_PIVOT_POLICY

RISK_FRACTION = Decimal(str(MID_SMALL_PIVOT_POLICY.risk_fraction_per_position))
MAXIMUM_AGGREGATE_RISK = Decimal(str(MID_SMALL_PIVOT_POLICY.maximum_aggregate_risk))


class PortfolioContractError(ValueError):
    """Raised when allocator input cannot safely be ranked."""


def _decimal(value: object, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise PortfolioContractError(f"{field} must be a finite decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise PortfolioContractError(f"{field} must be a finite decimal") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise PortfolioContractError(f"{field} must be a finite{' positive' if positive else ''} decimal")
    return result


def _canonical_text(value: object, field: str, *, uppercase: bool = False) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise PortfolioContractError(f"{field} must be canonical non-empty text")
    if uppercase and value != value.upper():
        raise PortfolioContractError(f"{field} must be uppercase")
    return value


@dataclass(frozen=True)
class PortfolioCandidate:
    candidate_id: uuid.UUID
    universe_snapshot_id: uuid.UUID
    ticker: str
    strategy_id: str
    strategy_version: str
    sector: str
    score: Decimal
    entry: Decimal
    stop: Decimal
    target: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, uuid.UUID):
            raise PortfolioContractError("candidate_id must be a UUID")
        if not isinstance(self.universe_snapshot_id, uuid.UUID):
            raise PortfolioContractError("universe_snapshot_id must be a UUID")
        _canonical_text(self.ticker, "ticker", uppercase=True)
        _canonical_text(self.strategy_id, "strategy_id")
        _canonical_text(self.strategy_version, "strategy_version")
        _canonical_text(self.sector, "sector")
        score = _decimal(self.score, "score")
        entry = _decimal(self.entry, "entry", positive=True)
        stop = _decimal(self.stop, "stop", positive=True)
        target = _decimal(self.target, "target", positive=True)
        if stop >= entry:
            raise PortfolioContractError("stop must be below entry")
        if target <= entry:
            raise PortfolioContractError("target must be above entry")
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "entry", entry)
        object.__setattr__(self, "stop", stop)
        object.__setattr__(self, "target", target)


@dataclass(frozen=True)
class ExistingPosition:
    ticker: str
    sector: str
    risk_fraction: Decimal = RISK_FRACTION

    def __post_init__(self) -> None:
        _canonical_text(self.ticker, "ticker", uppercase=True)
        _canonical_text(self.sector, "sector")
        risk = _decimal(self.risk_fraction, "risk_fraction", positive=True)
        if risk > RISK_FRACTION:
            raise PortfolioContractError("existing risk_fraction exceeds policy position risk")
        object.__setattr__(self, "risk_fraction", risk)


@dataclass(frozen=True)
class AllocationDecision:
    candidate: PortfolioCandidate
    global_rank: int
    sector_rank: int
    normalized_score: Decimal
    risk_fraction: Decimal
    selected: bool
    reason: str

    @property
    def ticker(self) -> str:
        return self.candidate.ticker


@dataclass(frozen=True)
class AllocationResult:
    decisions: tuple[AllocationDecision, ...]
    selected: tuple[AllocationDecision, ...]
    existing_positions: int
    existing_risk: Decimal
    aggregate_selected_risk: Decimal
    selected_sector_counts: dict[str, int]


def _normalized_scores(candidates: Sequence[PortfolioCandidate]) -> dict[uuid.UUID, Decimal]:
    """Min-max normalize within each strategy before one global comparison."""
    grouped: dict[tuple[str, str], list[PortfolioCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[(candidate.strategy_id, candidate.strategy_version)].append(candidate)
    normalized: dict[uuid.UUID, Decimal] = {}
    for group in grouped.values():
        low = min(item.score for item in group)
        high = max(item.score for item in group)
        for item in group:
            normalized[item.candidate_id] = (
                Decimal("1") if high == low else (item.score - low) / (high - low)
            )
    return normalized


def allocate_portfolio(
    candidates: Sequence[PortfolioCandidate],
    *,
    existing_positions: Iterable[ExistingPosition] = (),
) -> AllocationResult:
    """Globally rank and allocate one 5%-risk paper position per ticker.

    This pure pre-allocation is repeated under the database lock by the shared
    recommendation writer, which remains authoritative for concurrent capacity.
    """
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise PortfolioContractError("candidates must be a sequence")
    if any(not isinstance(item, PortfolioCandidate) for item in candidates):
        raise PortfolioContractError("every candidate must satisfy PortfolioCandidate")
    existing = tuple(existing_positions)
    if any(not isinstance(item, ExistingPosition) for item in existing):
        raise PortfolioContractError("every existing position must satisfy ExistingPosition")

    normalized = _normalized_scores(candidates)
    ranked = sorted(
        candidates,
        key=lambda item: (
            -normalized[item.candidate_id],
            -item.score,
            item.ticker,
            item.strategy_id,
            str(item.candidate_id),
        ),
    )
    active_tickers = {item.ticker for item in existing}
    sector_counts = Counter(item.sector for item in existing)
    existing_risk = sum((item.risk_fraction for item in existing), Decimal("0"))
    aggregate_risk = existing_risk
    strategy_sector_ranks: Counter[str] = Counter()
    decisions: list[AllocationDecision] = []
    selected: list[AllocationDecision] = []
    seen_candidate_tickers: set[str] = set()

    for global_rank, candidate in enumerate(ranked, start=1):
        strategy_sector_ranks[candidate.sector] += 1
        reason = "selected"
        is_selected = False
        if candidate.ticker in active_tickers or candidate.ticker in seen_candidate_tickers:
            reason = "duplicate_ticker"
        elif len(active_tickers) >= MID_SMALL_PIVOT_POLICY.maximum_positions:
            reason = "global_position_cap"
        elif sector_counts[candidate.sector] >= MID_SMALL_PIVOT_POLICY.maximum_positions_per_sector:
            reason = "sector_position_cap"
        elif aggregate_risk + RISK_FRACTION > MAXIMUM_AGGREGATE_RISK:
            reason = "aggregate_risk_cap"
        else:
            is_selected = True
            active_tickers.add(candidate.ticker)
            sector_counts[candidate.sector] += 1
            aggregate_risk += RISK_FRACTION
        seen_candidate_tickers.add(candidate.ticker)
        decision = AllocationDecision(
            candidate=candidate,
            global_rank=global_rank,
            sector_rank=strategy_sector_ranks[candidate.sector],
            normalized_score=normalized[candidate.candidate_id],
            risk_fraction=RISK_FRACTION,
            selected=is_selected,
            reason=reason,
        )
        decisions.append(decision)
        if is_selected:
            selected.append(decision)

    return AllocationResult(
        decisions=tuple(decisions),
        selected=tuple(selected),
        existing_positions=len(existing),
        existing_risk=existing_risk,
        aggregate_selected_risk=sum((item.risk_fraction for item in selected), Decimal("0")),
        selected_sector_counts=dict(Counter(item.candidate.sector for item in selected)),
    )
