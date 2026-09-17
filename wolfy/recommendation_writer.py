"""Serialized paper-recommendation capacity enforcement.

All Postgres recommendation writers use this module so approved and experimental
paths share one transaction-scoped lock and one post-lock capacity recount.
This module has no broker integration and performs no live actions.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Callable, Mapping, Sequence

GLOBAL_RECOMMENDATION_LOCK_KEY = "wolfy:global-paper-recommendations:v1"
MAXIMUM_POSITIONS = 20
MAXIMUM_POSITIONS_PER_SECTOR = 5
RISK_FRACTION_PER_POSITION = Decimal("0.05")
MAXIMUM_AGGREGATE_RISK = Decimal("1.00")
_ACTIVE_STATUSES = ("paper_candidate", "paper_logged")


@dataclass(frozen=True)
class RecommendationCandidate:
    ticker: str
    strategy_name: str
    signal_dt: date
    sector: str
    risk_fraction: Decimal

    def __post_init__(self) -> None:
        ticker = self.ticker.strip().upper() if isinstance(self.ticker, str) else ""
        strategy = self.strategy_name.strip() if isinstance(self.strategy_name, str) else ""
        sector = self.sector.strip() if isinstance(self.sector, str) else ""
        if not ticker or not strategy or not sector or type(self.signal_dt) is not date:
            raise ValueError("recommendation candidate identity fields must be present")
        try:
            risk = Decimal(self.risk_fraction)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("risk_fraction must be a finite decimal") from exc
        if not risk.is_finite() or risk <= 0 or risk > RISK_FRACTION_PER_POSITION:
            raise ValueError("risk_fraction must be positive and no greater than 0.05")
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "strategy_name", strategy)
        object.__setattr__(self, "sector", sector)
        object.__setattr__(self, "risk_fraction", risk)


@dataclass(frozen=True)
class RecommendationWriteResult:
    selected: tuple[RecommendationCandidate, ...]
    inserted: int
    blocked: tuple[tuple[str, str], ...]
    existing_positions: int
    existing_risk: Decimal
    dry_run: bool
    lock_key: str = GLOBAL_RECOMMENDATION_LOCK_KEY


def _safe_existing_risk(notes: Mapping[str, object]) -> Decimal:
    """Treat absent/malformed legacy risk as one full policy risk unit."""
    try:
        risk = Decimal(str(notes.get("risk_fraction", RISK_FRACTION_PER_POSITION)))
    except (InvalidOperation, TypeError, ValueError):
        return RISK_FRACTION_PER_POSITION
    if not risk.is_finite() or risk <= 0 or risk > RISK_FRACTION_PER_POSITION:
        return RISK_FRACTION_PER_POSITION
    return risk


def _active_portfolio(conn) -> tuple[set[str], Counter[str], Decimal]:
    rows = conn.execute(
        """SELECT r.ticker, r.notes
           FROM recommendations r
           WHERE r.status = ANY(%s)
             AND r.notes->>'paper_only'='true'
             AND r.notes->>'no_live_execution'='true'
             AND (
                 r.status='paper_candidate'
                 OR NOT EXISTS (
                     SELECT 1 FROM paper_trades closed_trade
                     WHERE closed_trade.recommendation_id=r.id::text
                       AND lower(closed_trade.status)='closed'
                 )
             )
           UNION ALL
           SELECT pt.ticker, coalesce(r.notes, pt.notes, '{}'::jsonb)
           FROM paper_trades pt
           LEFT JOIN recommendations r ON r.id::text=pt.recommendation_id
           WHERE lower(pt.status) IN ('open','pending','triggered','active')""",
        (list(_ACTIVE_STATUSES),),
    ).fetchall()
    tickers: set[str] = set()
    sectors: Counter[str] = Counter()
    aggregate_risk = Decimal("0")
    for ticker, raw_notes in rows:
        notes = raw_notes if isinstance(raw_notes, Mapping) else {}
        normalized_ticker = str(ticker).strip().upper()
        # A recommendation and its open paper trade are one position.
        if normalized_ticker in tickers:
            continue
        tickers.add(normalized_ticker)
        sector = str(notes.get("sector") or "Unknown").strip() or "Unknown"
        sectors[sector] += 1
        aggregate_risk += _safe_existing_risk(notes)
    return tickers, sectors, min(aggregate_risk, MAXIMUM_AGGREGATE_RISK)


def write_ranked_recommendations(
    conn,
    *,
    candidates: Sequence[RecommendationCandidate],
    insert_candidate: Callable[[RecommendationCandidate], bool],
    max_to_write: int,
    dry_run: bool,
) -> RecommendationWriteResult:
    """Select and optionally insert ranked candidates under shared global caps.

    Candidate order is ranking order and is intentionally preserved. On a real
    write the advisory transaction lock is acquired before the active portfolio
    is recounted and held by PostgreSQL until the caller commits or rolls back.
    A dry run performs only the read and never calls ``insert_candidate``.
    """
    if type(max_to_write) is not int:
        raise TypeError("max_to_write must be an integer")
    if not dry_run and getattr(conn, "autocommit", False):
        raise RuntimeError("shared recommendation writes require an explicit transaction")
    if not dry_run:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (GLOBAL_RECOMMENDATION_LOCK_KEY,),
        )
    active_tickers, sector_counts, aggregate_risk = _active_portfolio(conn)
    existing_positions = len(active_tickers)
    selected: list[RecommendationCandidate] = []
    blocked: list[tuple[str, str]] = []
    write_limit = min(max(0, max_to_write), MAXIMUM_POSITIONS)

    for candidate in candidates:
        if len(selected) >= write_limit:
            blocked.append((candidate.ticker, "writer_limit"))
            continue
        if candidate.ticker in active_tickers:
            blocked.append((candidate.ticker, "duplicate_ticker"))
            continue
        if len(active_tickers) >= MAXIMUM_POSITIONS:
            blocked.append((candidate.ticker, "global_position_cap"))
            continue
        if sector_counts[candidate.sector] >= MAXIMUM_POSITIONS_PER_SECTOR:
            blocked.append((candidate.ticker, "sector_position_cap"))
            continue
        if aggregate_risk + candidate.risk_fraction > MAXIMUM_AGGREGATE_RISK:
            blocked.append((candidate.ticker, "aggregate_risk_cap"))
            continue
        if not dry_run and not insert_candidate(candidate):
            blocked.append((candidate.ticker, "insert_conflict"))
            continue
        selected.append(candidate)
        active_tickers.add(candidate.ticker)
        sector_counts[candidate.sector] += 1
        aggregate_risk += candidate.risk_fraction

    return RecommendationWriteResult(
        selected=tuple(selected),
        inserted=0 if dry_run else len(selected),
        blocked=tuple(blocked),
        existing_positions=existing_positions,
        existing_risk=aggregate_risk - sum((item.risk_fraction for item in selected), Decimal("0")),
        dry_run=dry_run,
    )
