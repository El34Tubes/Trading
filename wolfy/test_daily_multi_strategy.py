from __future__ import annotations

from datetime import date
from decimal import Decimal
import uuid

from eod_readiness import EODReadiness, SourceMode
from test_db import test_connection


SNAPSHOT_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _readiness(*, publishable: bool = True) -> EODReadiness:
    reasons = () if publishable else ("benchmark_incomplete",)
    return EODReadiness(
        expected_session=date(2099, 5, 1),
        latest_complete_session=date(2099, 5, 1) if publishable else None,
        coverage_numerator=4 if publishable else 3,
        coverage_denominator=4,
        missing_symbols=() if publishable else ("SPY",),
        source_mode=SourceMode.FREE_T_PLUS_1,
        publishable=publishable,
        universe_snapshot_id=str(SNAPSHOT_ID),
        universe_policy_version="mid_small_multi_strategy_pivot_v1",
        universe_source_fingerprint="a" * 64,
        benchmark_coverage_numerator=3 if publishable else 2,
        benchmark_coverage_denominator=3,
        member_coverage_numerator=1,
        member_coverage_denominator=1,
        incomplete_reasons=reasons,
    )


def _candidate(ticker: str = "ZZPIVOT", *, sector: str = "Industrials"):
    from portfolio_allocator import PortfolioCandidate

    return PortfolioCandidate(
        candidate_id=uuid.uuid5(uuid.NAMESPACE_DNS, ticker),
        universe_snapshot_id=SNAPSHOT_ID,
        ticker=ticker,
        strategy_id="liquid_rs_breakout_close_confirm_1r",
        strategy_version="approved-2026-08-03",
        sector=sector,
        score=Decimal("2.5"),
        entry=Decimal("20"),
        stop=Decimal("19"),
        target=Decimal("22"),
    )


def test_incomplete_pipeline_fails_before_any_read_or_write():
    from daily_multi_strategy import run_underlying_pivot_slice

    class NoDatabaseAccess:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("incomplete pipeline touched the database")

    result = run_underlying_pivot_slice(
        NoDatabaseAccess(),
        signal_dt=date(2099, 5, 1),
        readiness=_readiness(publishable=False),
        candidates=[_candidate()],
        dry_run=False,
    )

    assert result["status"] == "pipeline_incomplete"
    assert result["recommendations_created"] == 0
    assert result["broker_orders_created"] == 0
    assert result["incomplete_reasons"] == ["benchmark_incomplete"]


def test_ready_approved_breakout_writes_stock_fallback_idempotently_in_wolfy_test():
    from daily_multi_strategy import run_underlying_pivot_slice

    ticker = f"ZZ{uuid.uuid4().hex[:8].upper()}"
    candidate = _candidate(ticker)
    with test_connection() as conn:
        try:
            first = run_underlying_pivot_slice(
                conn,
                signal_dt=date(2099, 5, 1),
                readiness=_readiness(),
                candidates=[candidate],
                dry_run=False,
            )
            second = run_underlying_pivot_slice(
                conn,
                signal_dt=date(2099, 5, 1),
                readiness=_readiness(),
                candidates=[candidate],
                dry_run=False,
            )
            row = conn.execute(
                "SELECT recommendation_type,status,notes FROM recommendations WHERE ticker=%s",
                (ticker,),
            ).fetchone()
        finally:
            conn.execute("DELETE FROM recommendations WHERE ticker=%s", (ticker,))

    assert first["status"] == "shadow_recommendations"
    assert first["recommendations_created"] == 1
    assert second["recommendations_created"] == 0
    assert second["status"] == "no_new_recommendations"
    assert row[0:2] == ("underlying_stock_fallback", "paper_candidate")
    assert row[2]["instrument_expression"] == "underlying_stock_fallback"
    assert row[2]["instrument_reason"] == "option_engine_not_release_ready"
    assert row[2]["risk_fraction"] == "0.05"
    assert row[2]["paper_only"] is True
    assert row[2]["no_live_execution"] is True
    assert row[2]["broker_order_submitted"] is False
    assert first["broker_orders_created"] == 0


def test_zero_candidates_and_research_only_candidates_do_not_publish():
    from daily_multi_strategy import run_underlying_pivot_slice

    class ReadOnlyEmptyConnection:
        def execute(self, statement, params=None):
            del statement, params
            raise AssertionError("empty or research-only candidate set touched database")

    empty = run_underlying_pivot_slice(
        ReadOnlyEmptyConnection(),
        signal_dt=date(2099, 5, 1),
        readiness=_readiness(),
        candidates=[],
        dry_run=False,
    )
    research = _candidate()
    object.__setattr__(research, "strategy_id", "mid_small_trend_pullback_reclaim_v1")
    blocked = run_underlying_pivot_slice(
        ReadOnlyEmptyConnection(),
        signal_dt=date(2099, 5, 1),
        readiness=_readiness(),
        candidates=[research],
        dry_run=False,
    )

    assert empty["status"] == "no_candidates"
    assert blocked["status"] == "no_candidates"
    assert blocked["research_only_blocked"] == 1
