from __future__ import annotations

from decimal import Decimal
import uuid

import pytest


def _candidate(
    ticker: str,
    score: str,
    sector: str = "Technology",
    *,
    strategy_id: str = "liquid_rs_breakout_close_confirm_1r",
):
    from portfolio_allocator import PortfolioCandidate

    return PortfolioCandidate(
        candidate_id=uuid.uuid5(uuid.NAMESPACE_DNS, f"{ticker}:{score}:{strategy_id}"),
        universe_snapshot_id=uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        ticker=ticker,
        strategy_id=strategy_id,
        strategy_version="approved-2026-08-03",
        sector=sector,
        score=Decimal(score),
        entry=Decimal("10"),
        stop=Decimal("9"),
        target=Decimal("12"),
    )


def test_allocator_globally_ranks_deduplicates_and_enforces_all_policy_caps():
    from portfolio_allocator import allocate_portfolio

    sectors = ("Technology", "Health Care", "Industrials", "Energy", "Financials")
    candidates = [
        _candidate(f"Z{index:02d}", str(100 - index), sectors[index % len(sectors)])
        for index in range(25)
    ]
    candidates.append(_candidate("Z00", "1", "Technology"))

    result = allocate_portfolio(candidates)

    assert len(result.selected) == 20
    assert result.aggregate_selected_risk == Decimal("1.00")
    assert all(decision.risk_fraction == Decimal("0.05") for decision in result.selected)
    assert len({decision.ticker for decision in result.selected}) == 20
    assert max(result.selected_sector_counts.values()) <= 5
    assert result.selected[0].ticker == "Z00"
    assert any(
        decision.ticker == "Z00" and decision.reason == "duplicate_ticker"
        for decision in result.decisions
        if not decision.selected
    )


def test_allocator_accounts_for_open_positions_sector_capacity_and_ties():
    from portfolio_allocator import ExistingPosition, allocate_portfolio

    existing = tuple(
        ExistingPosition(f"OPEN{index}", "Technology", Decimal("0.05"))
        for index in range(4)
    )
    candidates = [
        _candidate("BBB", "5", "Technology"),
        _candidate("AAA", "5", "Technology"),
        _candidate("CCC", "4", "Health Care"),
    ]

    result = allocate_portfolio(candidates, existing_positions=existing)

    assert [item.ticker for item in result.selected] == ["AAA", "CCC"]
    assert next(item for item in result.decisions if item.ticker == "BBB").reason == "sector_position_cap"
    assert result.existing_risk == Decimal("0.20")

    full = tuple(
        ExistingPosition(f"OPEN{index}", f"Sector {index}", Decimal("0.05"))
        for index in range(20)
    )
    blocked = allocate_portfolio([_candidate("NEW", "10")], existing_positions=full)
    assert blocked.selected == ()
    assert blocked.decisions[0].reason == "global_position_cap"


@pytest.mark.parametrize(
    "overrides",
    [
        {"score": Decimal("NaN")},
        {"ticker": " spy"},
        {"entry": Decimal("0")},
        {"stop": Decimal("10")},
        {"target": Decimal("10")},
        {"candidate_id": "not-a-uuid"},
    ],
)
def test_allocator_candidate_fails_closed_on_malformed_input(overrides):
    from portfolio_allocator import PortfolioCandidate, PortfolioContractError

    values = vars(_candidate("GOOD", "1")).copy()
    values.update(overrides)
    with pytest.raises(PortfolioContractError):
        PortfolioCandidate(**values)
