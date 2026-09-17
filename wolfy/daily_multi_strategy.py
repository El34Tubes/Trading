"""Minimal approved-breakout, underlying-only pivot vertical slice.

This module is deliberately shadow/test-only until exact option-chain integration
and the reviewed release gate land. It has no broker dependency or live action.
"""
from __future__ import annotations

from datetime import date
from typing import Sequence
import uuid

from portfolio_allocator import PortfolioCandidate, allocate_portfolio
from recommendation_writer import (
    UnderlyingFallback,
    write_underlying_fallback_recommendations,
)
from setup_evaluators import (
    APPROVED_BREAKOUT_STRATEGY_ID,
    APPROVED_BREAKOUT_STRATEGY_VERSION,
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
