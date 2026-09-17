from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from security_master import (
    DenylistObservation,
    RiskObservation,
    SecurityIdentityObservation,
    evaluate_security_eligibility,
)
from test_db import test_connection

UTC = timezone.utc
DECISION_AT = datetime(2026, 9, 17, 22, 0, tzinfo=UTC)


def identity(**changes) -> SecurityIdentityObservation:
    base = SecurityIdentityObservation(
        observation_id="polygon:AAPL:2026-09-17",
        ticker="AAPL",
        provider="polygon",
        source_url="https://api.polygon.io/v3/reference/tickers/AAPL",
        effective_from=DECISION_AT - timedelta(days=1),
        effective_to=None,
        observed_at=DECISION_AT - timedelta(hours=2),
        available_at=DECISION_AT - timedelta(hours=1),
        security_type="common_stock",
        locale="us",
        market="stocks",
        primary_exchange="NASDAQ",
        currency="USD",
        issuer_country="US",
        active=True,
        delisted_at=None,
        product_type=None,
        leveraged=False,
        inverse=False,
        single_stock_product=False,
    )
    return replace(base, **changes)


def evaluate(*observations, risks=(), denylist=(), decision_at=DECISION_AT):
    return evaluate_security_eligibility(
        ticker="AAPL",
        decision_at=decision_at,
        identity_observations=observations,
        risk_observations=risks,
        denylist_observations=denylist,
    )


def test_source_verified_us_common_stock_is_eligible():
    result = evaluate(identity())
    assert result.eligible is True
    assert result.reason_codes == ("eligible_us_common_stock",)
    assert result.identity_observation_ids == ("polygon:AAPL:2026-09-17",)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"security_type": "adr"}, "adr_or_depositary_receipt"),
        ({"issuer_country": "CN"}, "foreign_issuer"),
        ({"locale": "gb"}, "foreign_listing"),
        ({"market": "otc"}, "otc_security"),
        ({"primary_exchange": "OTCQX"}, "otc_security"),
        ({"security_type": "etf", "product_type": "etf"}, "etf_or_etp"),
        ({"product_type": "leveraged_etf", "leveraged": True}, "leveraged_product"),
        ({"product_type": "inverse_etf", "inverse": True}, "inverse_product"),
        ({"product_type": "single_stock_etf", "single_stock_product": True}, "single_stock_product"),
        ({"security_type": "preferred_stock"}, "preferred_stock"),
        ({"security_type": "unit"}, "unit"),
        ({"security_type": "right"}, "right"),
        ({"security_type": "warrant"}, "warrant"),
        ({"active": False}, "inactive_security"),
        ({"delisted_at": DECISION_AT - timedelta(days=1)}, "delisted_security"),
    ],
)
def test_absolute_identity_exclusions(changes, reason):
    result = evaluate(identity(**changes))
    assert result.eligible is False
    assert reason in result.reason_codes


@pytest.mark.parametrize(
    "changes",
    [
        {"security_type": None},
        {"locale": None},
        {"market": None},
        {"primary_exchange": None},
        {"currency": None},
        {"issuer_country": None},
        {"active": None},
    ],
)
def test_unknown_identity_fails_closed(changes):
    result = evaluate(identity(**changes))
    assert result.eligible is False
    assert "unknown_identity" in result.reason_codes


def test_conflicting_current_source_identity_fails_closed():
    conflicting = identity(
        observation_id="sec:conflict",
        provider="sec",
        source_url="https://www.sec.gov/example",
        issuer_country="CA",
    )
    result = evaluate(identity(), conflicting)
    assert result.eligible is False
    assert result.reason_codes == ("conflicting_identity",)


def test_future_unavailable_and_stale_sources_fail_closed():
    future = evaluate(identity(available_at=DECISION_AT + timedelta(seconds=1)))
    assert future.eligible is False
    assert future.reason_codes == ("identity_not_available_at_decision",)

    stale = evaluate(
        identity(
            effective_from=DECISION_AT - timedelta(days=60),
            observed_at=DECISION_AT - timedelta(days=31),
            available_at=DECISION_AT - timedelta(days=30),
        )
    )
    assert stale.eligible is False
    assert stale.reason_codes == ("stale_identity_source",)


def test_naive_decision_or_source_times_are_rejected():
    with pytest.raises(ValueError, match="decision_at must be timezone-aware"):
        evaluate(identity(), decision_at=DECISION_AT.replace(tzinfo=None))
    with pytest.raises(ValueError, match="available_at must be timezone-aware"):
        identity(available_at=DECISION_AT.replace(tzinfo=None))


def test_risk_vetoes_cannot_make_unknown_identity_eligible():
    manipulation = RiskObservation(
        observation_id="risk:manipulation",
        ticker="AAPL",
        risk_type="manipulation",
        decision="veto",
        reason_code="pump_promotion_risk",
        source="suspicious_activity",
        evidence={"flag": "low_float_price_spike"},
        effective_from=DECISION_AT - timedelta(days=1),
        effective_to=None,
        available_at=DECISION_AT - timedelta(minutes=1),
    )
    government = replace(
        manipulation,
        observation_id="risk:government",
        risk_type="government_interference",
        reason_code="state_interference_risk",
    )
    result = evaluate(identity(), risks=(manipulation, government))
    assert result.eligible is False
    assert result.reason_codes == (
        "government_interference_risk_veto",
        "manipulation_risk_veto",
    )

    clear = replace(manipulation, decision="clear")
    unknown = evaluate(risks=(clear,))
    assert unknown.eligible is False
    assert unknown.reason_codes == ("unknown_identity",)


def test_effective_dated_denylist_and_point_in_time_filtering():
    active = DenylistObservation(
        observation_id="deny:AAPL",
        ticker="AAPL",
        reason_code="user_manipulation_denylist",
        source="user_policy",
        effective_from=DECISION_AT - timedelta(days=1),
        effective_to=DECISION_AT + timedelta(days=1),
        available_at=DECISION_AT - timedelta(minutes=1),
    )
    assert evaluate(identity(), denylist=(active,)).reason_codes == ("denylisted",)
    expired = replace(active, effective_to=DECISION_AT - timedelta(seconds=1))
    future = replace(active, effective_from=DECISION_AT + timedelta(seconds=1))
    assert evaluate(identity(), denylist=(expired, future)).eligible is True


def test_ticker_mismatch_is_rejected_at_input_boundary():
    with pytest.raises(ValueError, match="ticker mismatch"):
        evaluate(identity(ticker="MSFT"))


def test_schema_is_append_only_and_constrained_in_wolfy_test():
    with test_connection() as conn:
        assert conn.execute("SELECT current_database()").fetchone()[0] == "wolfy_test"
        row = identity(ticker="ZZSEC")
        conn.execute(
            """INSERT INTO security_identity_observations(
                   observation_id,ticker,provider,source_url,effective_from,effective_to,
                   observed_at,available_at,security_type,locale,market,primary_exchange,
                   currency,issuer_country,active,delisted_at,product_type,leveraged,
                   inverse,single_stock_product,raw_source)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
            (
                row.observation_id,
                row.ticker,
                row.provider,
                row.source_url,
                row.effective_from,
                row.effective_to,
                row.observed_at,
                row.available_at,
                row.security_type,
                row.locale,
                row.market,
                row.primary_exchange,
                row.currency,
                row.issuer_country,
                row.active,
                row.delisted_at,
                row.product_type,
                row.leveraged,
                row.inverse,
                row.single_stock_product,
                "{}",
            ),
        )
        with pytest.raises(Exception, match="append-only"):
            conn.execute(
                "UPDATE security_identity_observations SET active=false WHERE observation_id=%s",
                (row.observation_id,),
            )
