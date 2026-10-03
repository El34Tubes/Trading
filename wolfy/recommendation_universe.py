"""Immutable point-in-time recommendation universe for the mid/small pivot."""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Sequence

from orchestration_config import MID_SMALL_PIVOT_POLICY, MidSmallPivotPolicy
from security_master import SecurityEligibilityDecision

_SNAPSHOT_NAMESPACE = uuid.UUID("f4134a24-0530-4e5c-b00d-d03a836fd468")


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _ticker(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or value != value.upper():
        raise ValueError("ticker must be non-empty uppercase canonical text")
    return value


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty canonical text")
    return value


def _decimal(value: object, name: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a finite decimal") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError(f"{name} must be a finite{' positive' if positive else ''} decimal")
    return result


@dataclass(frozen=True, slots=True)
class MarketCapObservation:
    observation_id: str
    ticker: str
    market_cap: Decimal
    provider: str
    source_url: str
    effective_at: datetime
    available_at: datetime

    def __post_init__(self) -> None:
        _text(self.observation_id, "observation_id")
        _ticker(self.ticker)
        object.__setattr__(self, "market_cap", _decimal(self.market_cap, "market_cap", positive=True))
        _text(self.provider, "provider")
        _text(self.source_url, "source_url")
        _aware(self.effective_at, "effective_at")
        _aware(self.available_at, "available_at")


@dataclass(frozen=True, slots=True)
class AdjustedDailyBarObservation:
    observation_id: str
    ticker: str
    session: date
    close: Decimal
    volume: int
    provider: str
    source_url: str
    available_at: datetime
    adjusted: bool

    def __post_init__(self) -> None:
        _text(self.observation_id, "observation_id")
        _ticker(self.ticker)
        if not isinstance(self.session, date) or isinstance(self.session, datetime):
            raise ValueError("session must be a date")
        object.__setattr__(self, "close", _decimal(self.close, "close", positive=True))
        if isinstance(self.volume, bool) or not isinstance(self.volume, int) or self.volume < 0:
            raise ValueError("volume must be a nonnegative integer")
        _text(self.provider, "provider")
        _text(self.source_url, "source_url")
        _aware(self.available_at, "available_at")
        if not isinstance(self.adjusted, bool):
            raise ValueError("adjusted must be boolean")


@dataclass(frozen=True, slots=True)
class UniverseSecurityEvidence:
    ticker: str
    sector: str
    identity_decision: SecurityEligibilityDecision
    market_cap_observations: tuple[MarketCapObservation, ...]
    bars: tuple[AdjustedDailyBarObservation, ...]

    def __post_init__(self) -> None:
        _ticker(self.ticker)
        _text(self.sector, "sector")
        rows = (*self.market_cap_observations, *self.bars)
        if self.identity_decision.ticker != self.ticker or any(row.ticker != self.ticker for row in rows):
            raise ValueError("ticker mismatch in universe evidence")


@dataclass(frozen=True, slots=True)
class UniverseMemberDecision:
    ticker: str
    sector: str
    included: bool
    reason_codes: tuple[str, ...]
    identity_observation_ids: tuple[str, ...]
    risk_observation_ids: tuple[str, ...]
    denylist_observation_ids: tuple[str, ...]
    market_cap_observation_id: str | None
    market_cap: Decimal | None
    bar_observation_ids: tuple[str, ...]
    close: Decimal | None
    average_dollar_volume: Decimal | None
    source_evidence_json: str
    facts_hash: str


@dataclass(frozen=True, slots=True)
class RecommendationUniverseSnapshot:
    snapshot_id: str
    signal_dt: date
    decision_at: datetime
    policy_version: str
    source_fingerprint: str
    included_count: int
    excluded_count: int
    decisions: tuple[UniverseMemberDecision, ...]

    @property
    def included_tickers(self) -> tuple[str, ...]:
        return tuple(row.ticker for row in self.decisions if row.included)


def _json_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _member_decision(
    item: UniverseSecurityEvidence,
    *,
    signal_dt: date,
    decision_at: datetime,
    policy: MidSmallPivotPolicy,
) -> UniverseMemberDecision:
    reasons: list[str] = []
    identity = item.identity_decision
    if identity.decision_at != decision_at:
        reasons.append("identity_decision_time_mismatch")
    if identity.eligible and (
        identity.reason_codes != ("eligible_us_common_stock",)
        or not identity.identity_observation_ids
    ):
        reasons.append("unknown_identity")
    if item.ticker in policy.benchmark_only:
        reasons.append("benchmark_context_only")
    elif not identity.eligible:
        reasons.extend(identity.reason_codes)

    available_caps = [
        row
        for row in item.market_cap_observations
        if row.available_at <= decision_at and row.effective_at <= decision_at
    ]
    selected_cap = max(available_caps, key=lambda row: (row.effective_at, row.available_at, row.observation_id)) if available_caps else None
    if selected_cap is None:
        if item.market_cap_observations and all(row.available_at > decision_at for row in item.market_cap_observations):
            reasons.append("market_cap_not_available_at_decision")
        else:
            reasons.append("missing_market_cap")
    elif selected_cap.market_cap < policy.market_cap_min:
        reasons.append("market_cap_below_minimum")
    elif selected_cap.market_cap > policy.market_cap_max:
        reasons.append("market_cap_above_maximum")

    available_bars = [
        row for row in item.bars if row.session <= signal_dt and row.available_at <= decision_at
    ]
    sessions = [row.session for row in available_bars]
    selected_bars: list[AdjustedDailyBarObservation] = []
    if len(sessions) != len(set(sessions)):
        reasons.append("duplicate_price_session")
    elif any(not row.adjusted for row in available_bars):
        reasons.append("unadjusted_price_bar")
    elif signal_dt not in sessions:
        if any(row.session == signal_dt and row.available_at > decision_at for row in item.bars):
            reasons.append("price_not_available_at_decision")
        else:
            reasons.append("missing_signal_date_price")
    elif len(available_bars) < policy.adv_sessions:
        reasons.append("insufficient_price_sessions")
    else:
        selected_bars = sorted(available_bars, key=lambda row: row.session)[-policy.adv_sessions :]

    close: Decimal | None = None
    adv: Decimal | None = None
    if selected_bars:
        close = selected_bars[-1].close
        adv = sum((row.close * Decimal(row.volume) for row in selected_bars), Decimal(0)) / Decimal(policy.adv_sessions)
        if close < policy.minimum_price:
            reasons.append("price_below_minimum")
        if adv < policy.minimum_average_dollar_volume:
            reasons.append("average_dollar_volume_below_minimum")

    reason_codes = tuple(sorted(set(reasons))) if reasons else ("eligible_mid_small_us_common_stock",)
    included = reason_codes == ("eligible_mid_small_us_common_stock",)
    source_evidence = {
        "identity_observation_ids": sorted(identity.identity_observation_ids),
        "risk_observation_ids": sorted(identity.risk_observation_ids),
        "denylist_observation_ids": sorted(identity.denylist_observation_ids),
        "market_cap": (
            {
                "observation_id": selected_cap.observation_id,
                "market_cap": str(selected_cap.market_cap),
                "provider": selected_cap.provider,
                "source_url": selected_cap.source_url,
                "effective_at": selected_cap.effective_at.isoformat(),
                "available_at": selected_cap.available_at.isoformat(),
            }
            if selected_cap
            else None
        ),
        "bars": [
            {
                "observation_id": row.observation_id,
                "session": row.session.isoformat(),
                "close": str(row.close),
                "volume": row.volume,
                "provider": row.provider,
                "source_url": row.source_url,
                "available_at": row.available_at.isoformat(),
                "adjusted": row.adjusted,
            }
            for row in selected_bars
        ],
    }
    source_evidence_json = json.dumps(
        source_evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    facts = {
        "ticker": item.ticker,
        "sector": item.sector,
        "included": included,
        "reasons": reason_codes,
        "source_evidence": source_evidence,
        "close": str(close) if close is not None else None,
        "adv": str(adv) if adv is not None else None,
    }
    return UniverseMemberDecision(
        ticker=item.ticker,
        sector=item.sector,
        included=included,
        reason_codes=reason_codes,
        identity_observation_ids=tuple(sorted(identity.identity_observation_ids)),
        risk_observation_ids=tuple(sorted(identity.risk_observation_ids)),
        denylist_observation_ids=tuple(sorted(identity.denylist_observation_ids)),
        market_cap_observation_id=selected_cap.observation_id if selected_cap else None,
        market_cap=selected_cap.market_cap if selected_cap else None,
        bar_observation_ids=tuple(row.observation_id for row in selected_bars),
        close=close,
        average_dollar_volume=adv,
        source_evidence_json=source_evidence_json,
        facts_hash=_json_hash(facts),
    )


def build_universe_snapshot(
    *,
    signal_dt: date,
    decision_at: datetime,
    evidence: Sequence[UniverseSecurityEvidence],
    policy: MidSmallPivotPolicy = MID_SMALL_PIVOT_POLICY,
) -> RecommendationUniverseSnapshot:
    """Build a deterministic snapshot from evidence knowable at ``decision_at``."""
    if not isinstance(signal_dt, date) or isinstance(signal_dt, datetime):
        raise ValueError("signal_dt must be a date")
    decision_time = _aware(decision_at, "decision_at")
    by_ticker: dict[str, UniverseSecurityEvidence] = {}
    for item in evidence:
        if item.ticker in by_ticker:
            raise ValueError(f"duplicate universe evidence for {item.ticker}")
        by_ticker[item.ticker] = item
    decisions = tuple(
        _member_decision(by_ticker[ticker], signal_dt=signal_dt, decision_at=decision_time, policy=policy)
        for ticker in sorted(by_ticker)
    )
    source_fingerprint = _json_hash(
        {
            "signal_dt": signal_dt.isoformat(),
            "decision_at": decision_time.isoformat(),
            "policy_version": policy.version,
            "members": [(row.ticker, row.facts_hash) for row in decisions],
        }
    )
    return RecommendationUniverseSnapshot(
        snapshot_id=str(uuid.uuid5(_SNAPSHOT_NAMESPACE, source_fingerprint)),
        signal_dt=signal_dt,
        decision_at=decision_time,
        policy_version=policy.version,
        source_fingerprint=source_fingerprint,
        included_count=sum(row.included for row in decisions),
        excluded_count=sum(not row.included for row in decisions),
        decisions=decisions,
    )


def persist_universe_snapshot(conn, snapshot: RecommendationUniverseSnapshot) -> None:
    """Persist one immutable snapshot; exact deterministic reruns are no-ops."""
    database = conn.execute("SELECT current_database()").fetchone()[0]
    if database != "wolfy_test":
        raise RuntimeError("universe snapshot writes are disabled outside wolfy_test before release gate")
    conn.execute(
        """INSERT INTO recommendation_universe_snapshots(
               snapshot_id,signal_dt,decision_at,policy_version,source_fingerprint,
               included_count,excluded_count)
             VALUES (%s,%s,%s,%s,%s,%s,%s)
             ON CONFLICT (snapshot_id) DO NOTHING""",
        (
            snapshot.snapshot_id,
            snapshot.signal_dt,
            snapshot.decision_at,
            snapshot.policy_version,
            snapshot.source_fingerprint,
            snapshot.included_count,
            snapshot.excluded_count,
        ),
    )
    for row in snapshot.decisions:
        conn.execute(
            """INSERT INTO recommendation_universe_members(
                   snapshot_id,ticker,sector,included,reason_codes,identity_observation_ids,
                   risk_observation_ids,denylist_observation_ids,market_cap_observation_id,
                   market_cap,bar_observation_ids,close,average_dollar_volume,
                   source_evidence,facts_hash)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                 ON CONFLICT (snapshot_id,ticker) DO NOTHING""",
            (
                snapshot.snapshot_id,
                row.ticker,
                row.sector,
                row.included,
                list(row.reason_codes),
                list(row.identity_observation_ids),
                list(row.risk_observation_ids),
                list(row.denylist_observation_ids),
                row.market_cap_observation_id,
                row.market_cap,
                list(row.bar_observation_ids),
                row.close,
                row.average_dollar_volume,
                row.source_evidence_json,
                row.facts_hash,
            ),
        )
    counts = conn.execute(
        """SELECT count(*) FILTER (WHERE included), count(*) FILTER (WHERE NOT included)
             FROM recommendation_universe_members WHERE snapshot_id=%s""",
        (snapshot.snapshot_id,),
    ).fetchone()
    if tuple(counts) != (snapshot.included_count, snapshot.excluded_count):
        raise RuntimeError("persisted universe snapshot conflicts with deterministic rerun")
