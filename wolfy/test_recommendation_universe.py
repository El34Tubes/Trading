from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from orchestration_config import MID_SMALL_PIVOT_POLICY
from recommendation_universe import (
    AdjustedDailyBarObservation,
    MarketCapObservation,
    UniverseSecurityEvidence,
    build_universe_snapshot,
    persist_universe_snapshot,
)
from security_master import SecurityEligibilityDecision
from test_db import test_connection

UTC = timezone.utc
SIGNAL_DT = date(2098, 6, 30)
DECISION_AT = datetime(2098, 6, 30, 22, 0, tzinfo=UTC)


def identity(ticker: str = "ZZELIG", *, eligible: bool = True, reason: str | None = None):
    return SecurityEligibilityDecision(
        ticker=ticker,
        decision_at=DECISION_AT,
        eligible=eligible,
        reason_codes=((reason or "eligible_us_common_stock"),),
        identity_observation_ids=(f"identity:{ticker}",),
        risk_observation_ids=(() if eligible else (f"risk:{ticker}",)),
        denylist_observation_ids=(),
    )


def cap(ticker: str = "ZZELIG", value: str = "200000000") -> MarketCapObservation:
    return MarketCapObservation(
        observation_id=f"cap:{ticker}:{value}",
        ticker=ticker,
        market_cap=Decimal(value),
        provider="massive",
        source_url=f"https://api.example.test/v3/reference/tickers/{ticker}",
        effective_at=DECISION_AT - timedelta(hours=3),
        available_at=DECISION_AT - timedelta(hours=2),
    )


def bars(
    ticker: str = "ZZELIG",
    *,
    count: int = 20,
    close: str = "3",
    volume: int = 1_666_667,
) -> tuple[AdjustedDailyBarObservation, ...]:
    first = SIGNAL_DT - timedelta(days=count - 1)
    return tuple(
        AdjustedDailyBarObservation(
            observation_id=f"bar:{ticker}:{first + timedelta(days=index)}",
            ticker=ticker,
            session=first + timedelta(days=index),
            close=Decimal(close),
            volume=volume,
            provider="massive",
            source_url=f"https://api.example.test/v2/aggs/{ticker}",
            available_at=DECISION_AT - timedelta(minutes=30),
            adjusted=True,
        )
        for index in range(count)
    )


def evidence(
    ticker: str = "ZZELIG",
    *,
    identity_decision: SecurityEligibilityDecision | None = None,
    market_caps: tuple[MarketCapObservation, ...] | None = None,
    price_bars: tuple[AdjustedDailyBarObservation, ...] | None = None,
) -> UniverseSecurityEvidence:
    return UniverseSecurityEvidence(
        ticker=ticker,
        sector="Industrials",
        identity_decision=identity_decision or identity(ticker),
        market_cap_observations=market_caps or (cap(ticker),),
        bars=price_bars or bars(ticker),
    )


@pytest.mark.parametrize("market_cap", ["200000000", "15000000000"])
def test_inclusive_market_cap_boundaries_are_eligible(market_cap):
    item = evidence(market_caps=(cap(value=market_cap),))
    snapshot = build_universe_snapshot(
        signal_dt=SIGNAL_DT, decision_at=DECISION_AT, evidence=(item,)
    )
    assert snapshot.included_tickers == ("ZZELIG",)
    assert snapshot.decisions[0].market_cap == Decimal(market_cap)


@pytest.mark.parametrize(
    ("market_cap", "close", "volume", "reason"),
    [
        ("199999999.99", "3", 1_666_667, "market_cap_below_minimum"),
        ("15000000000.01", "3", 1_666_667, "market_cap_above_maximum"),
        ("200000000", "2.99", 2_000_000, "price_below_minimum"),
        ("200000000", "3", 1_666_666, "average_dollar_volume_below_minimum"),
    ],
)
def test_just_outside_numeric_boundaries_fail_closed(market_cap, close, volume, reason):
    item = evidence(
        market_caps=(cap(value=market_cap),),
        price_bars=bars(close=close, volume=volume),
    )
    decision = build_universe_snapshot(
        signal_dt=SIGNAL_DT, decision_at=DECISION_AT, evidence=(item,)
    ).decisions[0]
    assert decision.included is False
    assert reason in decision.reason_codes


def test_exactly_twenty_adjusted_sessions_are_required_and_used_for_adv():
    nineteen = evidence(price_bars=bars(count=19, close="100", volume=100_000))
    decision = build_universe_snapshot(
        signal_dt=SIGNAL_DT, decision_at=DECISION_AT, evidence=(nineteen,)
    ).decisions[0]
    assert decision.reason_codes == ("insufficient_price_sessions",)

    rows = list(bars(close="4", volume=1_250_000))
    rows[0] = replace(rows[0], close=Decimal("8"), volume=625_000)
    decision = build_universe_snapshot(
        signal_dt=SIGNAL_DT,
        decision_at=DECISION_AT,
        evidence=(evidence(price_bars=tuple(rows)),),
    ).decisions[0]
    assert decision.included is True
    assert decision.average_dollar_volume == Decimal("5000000")


def test_future_market_cap_duplicate_or_unadjusted_bars_fail_closed():
    future_cap = replace(cap(), available_at=DECISION_AT + timedelta(seconds=1))
    decision = build_universe_snapshot(
        signal_dt=SIGNAL_DT,
        decision_at=DECISION_AT,
        evidence=(evidence(market_caps=(future_cap,)),),
    ).decisions[0]
    assert decision.reason_codes == ("market_cap_not_available_at_decision",)

    duplicate = bars() + (replace(bars()[0], observation_id="duplicate"),)
    decision = build_universe_snapshot(
        signal_dt=SIGNAL_DT,
        decision_at=DECISION_AT,
        evidence=(evidence(price_bars=duplicate),),
    ).decisions[0]
    assert decision.reason_codes == ("duplicate_price_session",)

    unadjusted = tuple(replace(row, adjusted=False) for row in bars())
    decision = build_universe_snapshot(
        signal_dt=SIGNAL_DT,
        decision_at=DECISION_AT,
        evidence=(evidence(price_bars=unadjusted),),
    ).decisions[0]
    assert decision.reason_codes == ("unadjusted_price_bar",)


def test_benchmarks_and_all_security_risk_exclusions_remain_excluded():
    items = [evidence("SPY")]
    for index, reason in enumerate(
        ("adr_or_depositary_receipt", "otc_security", "etf_or_etp", "denylisted", "manipulation_risk_veto", "government_interference_risk_veto")
    ):
        ticker = f"ZZBAD{index}"
        items.append(evidence(ticker, identity_decision=identity(ticker, eligible=False, reason=reason)))
    snapshot = build_universe_snapshot(
        signal_dt=SIGNAL_DT, decision_at=DECISION_AT, evidence=tuple(items)
    )
    assert snapshot.included_tickers == ()
    assert snapshot.decisions[0].reason_codes == ("benchmark_context_only",)
    assert {row.reason_codes[0] for row in snapshot.decisions[1:]} == {
        "adr_or_depositary_receipt",
        "otc_security",
        "etf_or_etp",
        "denylisted",
        "manipulation_risk_veto",
        "government_interference_risk_veto",
    }


def test_snapshot_members_reasons_count_and_fingerprint_are_deterministic():
    first = evidence("ZZB")
    second = evidence("ZZA")
    a = build_universe_snapshot(
        signal_dt=SIGNAL_DT, decision_at=DECISION_AT, evidence=(first, second)
    )
    b = build_universe_snapshot(
        signal_dt=SIGNAL_DT, decision_at=DECISION_AT, evidence=(second, first)
    )
    assert a == b
    assert a.included_tickers == ("ZZA", "ZZB")
    assert a.included_count == 2
    assert len(a.source_fingerprint) == 64
    assert a.policy_version == MID_SMALL_PIVOT_POLICY.version

    changed_source = evidence(
        "ZZA",
        market_caps=(replace(cap("ZZA"), source_url="https://different.example.test/cap"),),
    )
    changed = build_universe_snapshot(
        signal_dt=SIGNAL_DT, decision_at=DECISION_AT, evidence=(first, changed_source)
    )
    assert changed.source_fingerprint != a.source_fingerprint


def test_snapshot_is_persisted_immutably_and_eod_adapter_reads_members():
    from eod_signals import recommendation_universe_tickers

    snapshot = build_universe_snapshot(
        signal_dt=SIGNAL_DT, decision_at=DECISION_AT, evidence=(evidence(),)
    )
    with test_connection() as conn:
        assert conn.execute("SELECT current_database()").fetchone()[0] == "wolfy_test"
        persist_universe_snapshot(conn, snapshot)
        persist_universe_snapshot(conn, snapshot)
        assert recommendation_universe_tickers(conn, signal_dt=SIGNAL_DT) == ["ZZELIG"]
        assert recommendation_universe_tickers(
            conn, signal_dt=SIGNAL_DT, explicit_tickers=("zzelig",)
        ) == ["ZZELIG"]
        with pytest.raises(ValueError, match="failed universe policy: SPY"):
            recommendation_universe_tickers(
                conn, signal_dt=SIGNAL_DT, explicit_tickers=("ZZELIG", "SPY")
            )
        with pytest.raises(Exception, match="append-only"):
            conn.execute(
                "UPDATE recommendation_universe_members SET included=false WHERE snapshot_id=%s",
                (snapshot.snapshot_id,),
            )


def test_naive_decision_time_and_mismatched_evidence_fail_at_boundary():
    with pytest.raises(ValueError, match="decision_at must be timezone-aware"):
        build_universe_snapshot(
            signal_dt=SIGNAL_DT,
            decision_at=DECISION_AT.replace(tzinfo=None),
            evidence=(evidence(),),
        )
    with pytest.raises(ValueError, match="ticker mismatch"):
        evidence_rows = evidence("ZZELIG", market_caps=(cap("ZZOTHER"),))
        build_universe_snapshot(
            signal_dt=SIGNAL_DT, decision_at=DECISION_AT, evidence=(evidence_rows,)
        )
