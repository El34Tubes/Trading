"""Fail-closed Task 23 adapter for Wolfy's bounded production-paper release.

Only the already-approved close-confirmed breakout sleeve can cross this boundary.
The adapter has no broker or delivery integration.  General universe/candidate
writers remain restricted to ``wolfy_test``; the private bootstrap capability in
this module is the sole production persistence path for its exact source cache.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence
import uuid

from orchestration_config import MID_SMALL_PIVOT_POLICY

MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_RELEASE_ARTIFACT = MODULE_DIR / "config" / "mid_small_production_release.json"
RELEASE_SCHEMA = "wolfy-mid-small-production-release-v1"
EVIDENCE_SCHEMA = "wolfy-mid-small-canary-evidence-v1"
ROLLBACK_SCHEMA = "wolfy-mid-small-production-state-v1"
SOURCE_CACHE_SCHEMA = "wolfy-mid-small-source-cache-v1"
APPROVED_STRATEGY = "close_confirmed_breakout"
APPROVED_STRATEGY_ID = "liquid_rs_breakout_close_confirm_1r"
APPROVED_STRATEGY_VERSION = "approved-2026-08-03"
CONFIG_VERSION = "mid-small-paper-canary-v1"
_HASH = re.compile(r"[0-9a-f]{64}")
_UUID_NAMESPACE = uuid.UUID("f4134a24-0530-4e5c-b00d-d03a836fd468")
_CANDIDATE_NAMESPACE = uuid.UUID("97823487-9278-492d-83cd-957102c2cb29")
_EXCHANGES = {
    "XNAS": "NASDAQ",
    "XNYS": "NYSE",
    "XASE": "NYSE_AMERICAN",
    "ARCX": "NYSE",
    "BATS": "CBOE",
    "XCBO": "CBOE",
}
_SCOPE_FIELDS = (
    "config_version",
    "database",
    "policy_version",
    "signal_dt",
    "snapshot_fingerprint",
    "snapshot_id",
    "strategy",
    "strategy_id",
    "strategy_version",
)


class ProductionReleaseError(RuntimeError):
    """A release input or observed side effect violated the fixed contract."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _json_hash(value: object) -> str:
    return _sha256_bytes(_json_bytes(value))


def _canonical_hash(value: object, field: str) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise ProductionReleaseError(f"{field} must be canonical lowercase SHA-256")
    return value


def _exact_bool(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ProductionReleaseError(f"{field} must be boolean")
    return value


def _positive_decimal(value: object, field: str, *, allow_zero: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise ProductionReleaseError(f"{field} must be a finite decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ProductionReleaseError(f"{field} must be a finite decimal") from exc
    if not result.is_finite() or result < 0 or (not allow_zero and result == 0):
        raise ProductionReleaseError(f"{field} must be {'nonnegative' if allow_zero else 'positive'}")
    return result


def _canonical_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProductionReleaseError(f"{field} must be a non-empty canonical path")
    return value


def _scope_fingerprint(payload: Mapping[str, object]) -> str:
    return _json_hash({field: payload[field] for field in _SCOPE_FIELDS})


def _atomic_json(path: str | Path, payload: Mapping[str, object]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":")) + "\n"
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(encoded, encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


@dataclass(frozen=True, slots=True)
class ProductionRelease:
    schema_version: str
    enabled: bool
    database: str
    config_version: str
    strategy: str
    strategy_id: str
    strategy_version: str
    policy_version: str
    snapshot_id: str
    snapshot_fingerprint: str
    signal_dt: date
    publisher_count: int
    account_equity: Decimal
    stock_fallback_enabled: bool
    paper_only: bool
    no_live_execution: bool
    broker_execution_enabled: bool
    external_delivery_enabled: bool
    previous_publisher: str
    canary_evidence_path: str
    rollback_state_path: str
    scope_fingerprint: str

    @property
    def risk_fraction(self) -> str:
        return "0.05"

    @property
    def maximum_positions(self) -> int:
        return 20

    @property
    def maximum_positions_per_sector(self) -> int:
        return 5

    @property
    def maximum_aggregate_risk(self) -> str:
        return "1.00"


_REQUIRED_RELEASE_FIELDS = frozenset(
    {
        "schema_version", "enabled", "database", "config_version", "strategy",
        "strategy_id", "strategy_version", "policy_version", "snapshot_id",
        "snapshot_fingerprint", "signal_dt", "publisher_count", "account_equity",
        "stock_fallback_enabled", "paper_only", "no_live_execution",
        "broker_execution_enabled", "external_delivery_enabled", "previous_publisher",
        "canary_evidence_path", "rollback_state_path", "scope_fingerprint",
    }
)


def load_release_artifact(
    artifact_path: str | Path = DEFAULT_RELEASE_ARTIFACT, *, require_enabled: bool = True
) -> ProductionRelease:
    """Load and strictly validate the immutable exact-scope release artifact."""
    path = Path(artifact_path)
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionReleaseError(f"release artifact is unreadable: {path}") from exc
    if not isinstance(payload, dict) or set(payload) != _REQUIRED_RELEASE_FIELDS:
        raise ProductionReleaseError("release artifact fields do not match the v1 schema")
    if payload["schema_version"] != RELEASE_SCHEMA:
        raise ProductionReleaseError("unsupported release artifact schema_version")
    enabled = _exact_bool(payload["enabled"], "enabled")
    if require_enabled and not enabled:
        raise ProductionReleaseError("production release is disabled")
    fixed = {
        "database": "wolfy",
        "config_version": CONFIG_VERSION,
        "strategy": APPROVED_STRATEGY,
        "strategy_id": APPROVED_STRATEGY_ID,
        "strategy_version": APPROVED_STRATEGY_VERSION,
        "policy_version": MID_SMALL_PIVOT_POLICY.version,
    }
    for field, expected in fixed.items():
        if payload[field] != expected:
            if field == "database":
                raise ProductionReleaseError("release requires exact database wolfy")
            if field == "strategy":
                raise ProductionReleaseError("only close_confirmed_breakout may publish")
            raise ProductionReleaseError(f"release {field} differs from the approved scope")
    try:
        snapshot = uuid.UUID(str(payload["snapshot_id"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ProductionReleaseError("snapshot_id must be a canonical UUID") from exc
    if str(snapshot) != payload["snapshot_id"]:
        raise ProductionReleaseError("snapshot_id must be a canonical UUID")
    snapshot_fingerprint = _canonical_hash(payload["snapshot_fingerprint"], "snapshot_fingerprint")
    scope = _canonical_hash(payload["scope_fingerprint"], "scope_fingerprint")
    expected_scope = _scope_fingerprint(payload)
    if scope != expected_scope:
        raise ProductionReleaseError(
            "scope_fingerprint does not bind snapshot_fingerprint and exact release scope"
        )
    try:
        signal_dt = date.fromisoformat(payload["signal_dt"])
    except (TypeError, ValueError) as exc:
        raise ProductionReleaseError("signal_dt must be an ISO date") from exc
    if type(payload["publisher_count"]) is not int or payload["publisher_count"] != 1:
        raise ProductionReleaseError("publisher_count must equal one")
    safety = {
        "stock_fallback_enabled": True,
        "paper_only": True,
        "no_live_execution": True,
        "broker_execution_enabled": False,
        "external_delivery_enabled": False,
    }
    for field, expected in safety.items():
        actual = _exact_bool(payload[field], field)
        if actual is not expected:
            label = "broker execution" if field == "broker_execution_enabled" else field
            raise ProductionReleaseError(f"unsafe {label} setting")
    equity = _positive_decimal(payload["account_equity"], "account_equity", allow_zero=not enabled)
    if enabled and equity <= 0:
        raise ProductionReleaseError("enabled release requires positive account_equity")
    previous = payload["previous_publisher"]
    if not isinstance(previous, str) or not previous or previous != previous.strip():
        raise ProductionReleaseError("previous_publisher must be canonical text")
    return ProductionRelease(
        schema_version=RELEASE_SCHEMA,
        enabled=enabled,
        database="wolfy",
        config_version=CONFIG_VERSION,
        strategy=APPROVED_STRATEGY,
        strategy_id=APPROVED_STRATEGY_ID,
        strategy_version=APPROVED_STRATEGY_VERSION,
        policy_version=MID_SMALL_PIVOT_POLICY.version,
        snapshot_id=str(snapshot),
        snapshot_fingerprint=snapshot_fingerprint,
        signal_dt=signal_dt,
        publisher_count=1,
        account_equity=equity,
        stock_fallback_enabled=True,
        paper_only=True,
        no_live_execution=True,
        broker_execution_enabled=False,
        external_delivery_enabled=False,
        previous_publisher=previous,
        canary_evidence_path=_canonical_path(payload["canary_evidence_path"], "canary_evidence_path"),
        rollback_state_path=_canonical_path(payload["rollback_state_path"], "rollback_state_path"),
        scope_fingerprint=scope,
    )


def validate_production_connection(conn) -> None:
    """Require the exact local peer-authenticated ``root`` -> ``wolfy`` target."""
    info = getattr(conn, "info", None)
    if (
        info is None
        or getattr(info, "dbname", None) != "wolfy"
        or getattr(info, "user", None) != "root"
        or getattr(info, "host", None) != "/var/run/postgresql"
    ):
        raise ProductionReleaseError(
            "release requires exact production database wolfy over local root peer connection"
        )
    row = conn.execute("SELECT current_database()").fetchone()
    if row is None or row[0] != "wolfy":
        raise ProductionReleaseError("release requires exact production database wolfy")


def verify_snapshot_preflight(conn, release: ProductionRelease) -> int:
    """Bind publication to one immutable, nonempty, source-verified snapshot."""
    row = conn.execute(
        """SELECT snapshot_id::text,signal_dt,policy_version,source_fingerprint,included_count
             FROM recommendation_universe_snapshots WHERE snapshot_id=%s""",
        (release.snapshot_id,),
    ).fetchone()
    expected = (
        release.snapshot_id,
        release.signal_dt,
        release.policy_version,
        release.snapshot_fingerprint,
    )
    if row is None or tuple(row[:4]) != expected or type(row[4]) is not int or row[4] <= 0:
        raise ProductionReleaseError("exact immutable snapshot binding failed or snapshot is empty")
    counts = conn.execute(
        """SELECT count(*),count(*) FILTER (
                 WHERE NOT included
                    OR coalesce(source_evidence#>>'{identity,issuer_country}','') <> 'US'
                    OR coalesce(source_evidence#>>'{identity,security_type}','') <> 'common_stock'
                    OR cardinality(identity_observation_ids)=0)
             FROM recommendation_universe_members
            WHERE snapshot_id=%s AND included""",
        (release.snapshot_id,),
    ).fetchone()
    if counts is None or counts[0] != row[4]:
        raise ProductionReleaseError("snapshot member count differs from immutable header")
    if counts[1] != 0:
        raise ProductionReleaseError("included members require source-verified issuer country and identity")
    return int(row[4])


def _canonical_ids(value: object, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ProductionReleaseError("recommendation_ids must be a sequence")
    if not value and not allow_empty:
        raise ProductionReleaseError("actionable canary requires a real recommendation set")
    result: list[str] = []
    for item in value:
        try:
            parsed = uuid.UUID(str(item))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ProductionReleaseError("recommendation_ids must contain UUIDs") from exc
        if str(parsed) != item:
            raise ProductionReleaseError("recommendation_ids must contain canonical UUIDs")
        result.append(item)
    if len(set(result)) != len(result):
        raise ProductionReleaseError("recommendation_ids must be unique")
    return tuple(result)


def _validate_publication(release: ProductionRelease, payload: Mapping[str, object], *, phase: str) -> tuple[str, ...]:
    if not isinstance(payload, Mapping):
        raise ProductionReleaseError(f"{phase} callback did not return an object")
    decision = payload.get("decision", "actionable")
    if decision not in {"actionable", "no_trade"}:
        raise ProductionReleaseError("canary decision must be actionable or no_trade")
    ids = _canonical_ids(payload.get("recommendation_ids"), allow_empty=decision == "no_trade")
    if (decision == "no_trade") != (len(ids) == 0):
        raise ProductionReleaseError("canary decision and recommendation_ids are inconsistent")
    integers = (
        "recommendations_created", "positions_total", "maximum_sector_positions",
        "research_only_published", "broker_orders_created", "external_deliveries",
    )
    for field in integers:
        if type(payload.get(field)) is not int or int(payload[field]) < 0:
            raise ProductionReleaseError(f"{field} must be a nonnegative integer")
    if payload["broker_orders_created"] != 0:
        raise ProductionReleaseError("broker_orders_created must remain zero")
    if payload["external_deliveries"] != 0:
        raise ProductionReleaseError("external_deliveries must remain zero")
    if payload["research_only_published"] != 0:
        raise ProductionReleaseError("research sleeves cannot publish")
    if payload["positions_total"] > release.maximum_positions:
        raise ProductionReleaseError("maximum position cap exceeded")
    if payload["maximum_sector_positions"] > release.maximum_positions_per_sector:
        raise ProductionReleaseError("maximum sector position cap exceeded")
    if payload.get("paper_only") is not True or payload.get("no_live_execution") is not True:
        raise ProductionReleaseError("canary output must remain paper-only with no live execution")
    if payload.get("exact_chain_or_stock_fallback") is not True:
        raise ProductionReleaseError("every recommendation requires an exact chain or explicit stock fallback")
    risks = payload.get("risk_fractions")
    if not isinstance(risks, Sequence) or isinstance(risks, (str, bytes)):
        raise ProductionReleaseError("risk_fractions must be a sequence")
    if len(risks) != payload["positions_total"]:
        raise ProductionReleaseError("risk_fractions must cover the complete active portfolio")
    try:
        parsed_risks = tuple(Decimal(str(item)) for item in risks)
        aggregate = Decimal(str(payload.get("aggregate_risk")))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ProductionReleaseError("risk values must be finite decimals") from exc
    if any(not item.is_finite() or item <= 0 or item > Decimal(release.risk_fraction) for item in parsed_risks):
        raise ProductionReleaseError("per-position risk cap exceeded")
    if not aggregate.is_finite() or aggregate != sum(parsed_risks, Decimal(0)):
        raise ProductionReleaseError("aggregate_risk does not match active positions")
    if aggregate > Decimal(release.maximum_aggregate_risk):
        raise ProductionReleaseError("aggregate risk cap exceeded")
    return ids


def execute_canary_callbacks(
    release: ProductionRelease,
    *,
    publish: Callable[..., Mapping[str, object]],
    readback: Callable[[], Mapping[str, object]],
) -> dict[str, object]:
    """Publish, rerun, and independently read back one real bounded canary."""
    first = publish(rerun=False)
    first_ids = _validate_publication(release, first, phase="initial publish")
    if first.get("decision", "actionable") == "actionable" and first["recommendations_created"] <= 0:
        raise ProductionReleaseError("actionable initial canary must create recommendations")
    if first.get("decision") == "no_trade" and first["recommendations_created"] != 0:
        raise ProductionReleaseError("no-trade canary cannot create recommendations")
    second = publish(rerun=True)
    second_ids = _validate_publication(release, second, phase="idempotent rerun")
    if second["recommendations_created"] != 0 or second_ids != first_ids:
        raise ProductionReleaseError("canary rerun was not idempotent")
    durable = readback()
    durable_ids = _validate_publication(release, durable, phase="durable readback")
    if durable["recommendations_created"] != 0 or durable_ids != first_ids:
        raise ProductionReleaseError("durable readback differs from canary publication")
    return {
        "schema_version": EVIDENCE_SCHEMA,
        "passed": True,
        "snapshot_id": release.snapshot_id,
        "snapshot_fingerprint": release.snapshot_fingerprint,
        "scope_fingerprint": release.scope_fingerprint,
        "config_version": release.config_version,
        "publisher_count": release.publisher_count,
        "recommendation_ids": list(first_ids),
        "decision": first.get("decision", "actionable"),
        "recommendations_created": first["recommendations_created"],
        "positions_total": durable["positions_total"],
        "maximum_sector_positions": durable["maximum_sector_positions"],
        "risk_fractions": list(durable["risk_fractions"]),
        "aggregate_risk": durable["aggregate_risk"],
        "research_only_published": 0,
        "exact_chain_or_stock_fallback": True,
        "paper_only": True,
        "no_live_execution": True,
        "broker_orders_created": 0,
        "external_deliveries": 0,
        "idempotent_rerun": True,
    }


def execute_scheduled_callbacks(
    release: ProductionRelease,
    *,
    publish: Callable[..., Mapping[str, object]],
    readback: Callable[[], Mapping[str, object]],
    canary_evidence: Mapping[str, object],
) -> dict[str, object]:
    """Validate an authorized recurring invocation for the exact canary scope."""
    expected_ids_raw = canary_evidence.get("recommendation_ids")
    if not isinstance(expected_ids_raw, list) or any(not isinstance(value, str) for value in expected_ids_raw):
        raise ProductionReleaseError("canary evidence recommendation_ids are malformed")
    expected_ids = tuple(expected_ids_raw)
    published = publish(rerun=True)
    published_ids = _validate_publication(release, published, phase="scheduled idempotent publish")
    if published["recommendations_created"] != 0:
        raise ProductionReleaseError("scheduled exact-snapshot invocation created recommendations after canary")
    if published_ids != expected_ids:
        raise ProductionReleaseError("scheduled publication differs from authorized canary scope")
    durable = readback()
    durable_ids = _validate_publication(release, durable, phase="scheduled durable readback")
    if durable["recommendations_created"] != 0 or durable_ids != expected_ids:
        raise ProductionReleaseError("scheduled durable readback differs from authorized canary scope")
    return {
        "schema_version": EVIDENCE_SCHEMA,
        "passed": True,
        "scheduled": True,
        "snapshot_id": release.snapshot_id,
        "snapshot_fingerprint": release.snapshot_fingerprint,
        "config_version": release.config_version,
        "recommendation_ids": list(durable_ids),
        "recommendations_created": 0,
        "decision": durable.get("decision", "actionable" if durable_ids else "no_trade"),
        "positions_total": durable["positions_total"],
        "maximum_sector_positions": durable["maximum_sector_positions"],
        "risk_fractions": list(durable["risk_fractions"]),
        "aggregate_risk": durable["aggregate_risk"],
        "research_only_published": 0,
        "exact_chain_or_stock_fallback": True,
        "paper_only": True,
        "no_live_execution": True,
        "broker_orders_created": 0,
        "external_deliveries": 0,
        "idempotent_rerun": True,
    }


def persist_canary_evidence(
    release: ProductionRelease,
    artifact_path: str | Path,
    evidence: Mapping[str, object],
) -> dict[str, object]:
    """Atomically persist evidence bound to the exact artifact bytes."""
    if evidence.get("passed") is not True or evidence.get("schema_version") != EVIDENCE_SCHEMA:
        raise ProductionReleaseError("only passed v1 canary evidence may be persisted")
    payload = dict(evidence)
    payload["artifact_sha256"] = _sha256_bytes(Path(artifact_path).read_bytes())
    payload["persisted_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_json(release.canary_evidence_path, payload)
    return payload


def _load_json_object(path: str | Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionReleaseError(f"{label} is missing or unreadable") from exc
    if not isinstance(value, dict):
        raise ProductionReleaseError(f"{label} must be a JSON object")
    return value


def authorize_scheduled_production(
    release: ProductionRelease, artifact_path: str | Path = DEFAULT_RELEASE_ARTIFACT
) -> dict[str, object]:
    """Authorize one scheduled invocation only after exact durable canary evidence."""
    state_path = Path(release.rollback_state_path)
    if state_path.exists():
        state = _load_json_object(state_path, "rollback state")
        if state.get("enabled") is False:
            raise ProductionReleaseError("production release was rolled back")
        raise ProductionReleaseError("rollback state is malformed")
    evidence = _load_json_object(release.canary_evidence_path, "canary evidence")
    expected = {
        "schema_version": EVIDENCE_SCHEMA,
        "passed": True,
        "artifact_sha256": _sha256_bytes(Path(artifact_path).read_bytes()),
        "snapshot_id": release.snapshot_id,
        "snapshot_fingerprint": release.snapshot_fingerprint,
        "config_version": release.config_version,
        "publisher_count": 1,
        "broker_orders_created": 0,
        "external_deliveries": 0,
    }
    for field, value in expected.items():
        if evidence.get(field) != value:
            raise ProductionReleaseError(f"canary evidence does not authorize scheduled mode: {field}")
    return {
        "authorized": True,
        "paper_only": True,
        "no_live_execution": True,
        "publisher_count": 1,
        "artifact_sha256": expected["artifact_sha256"],
    }


def rollback_release(
    release: ProductionRelease, artifact_path: str | Path = DEFAULT_RELEASE_ARTIFACT
) -> dict[str, object]:
    """Disable future scheduled runs without deleting recommendations or evidence."""
    state = {
        "schema_version": ROLLBACK_SCHEMA,
        "enabled": False,
        "scope_fingerprint": release.scope_fingerprint,
        "artifact_sha256": _sha256_bytes(Path(artifact_path).read_bytes()),
        "previous_publisher": release.previous_publisher,
        "previous_publisher_restored": True,
        "rows_deleted": 0,
        "rolled_back_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_json(release.rollback_state_path, state)
    return state


@dataclass(frozen=True, slots=True)
class SourceCache:
    path: Path
    sha256: str
    fetched_at: datetime
    massive_source_url: str
    nasdaq_source_url: str
    massive_rows: Mapping[str, Mapping[str, object]]
    nasdaq_rows: Mapping[str, Mapping[str, object]]


def _parse_utc_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ProductionReleaseError(f"{field} must be an ISO UTC timestamp")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    # Python accepts at most microseconds consistently; truncate provider nanos.
    if "." in text:
        prefix, suffix = text.split(".", 1)
        offset_index = min((i for i in (suffix.find("+"), suffix.find("-")) if i >= 0), default=len(suffix))
        fraction, offset = suffix[:offset_index], suffix[offset_index:]
        text = f"{prefix}.{fraction[:6]}{offset}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ProductionReleaseError(f"{field} must be an ISO UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ProductionReleaseError(f"{field} must be an ISO UTC timestamp")
    return parsed


def load_source_cache(path: str | Path) -> SourceCache:
    """Validate the supplied immutable Massive/Nasdaq bulk evidence cache."""
    source = Path(path)
    try:
        raw = source.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionReleaseError("source cache is unreadable") from exc
    if not isinstance(payload, dict) or set(payload) != {"fetched_at", "massive", "nasdaq"}:
        raise ProductionReleaseError("source cache fields are malformed")
    massive, nasdaq = payload["massive"], payload["nasdaq"]
    if not isinstance(massive, dict) or not isinstance(nasdaq, dict):
        raise ProductionReleaseError("source cache provider payloads must be objects")
    massive_required = {"page_count", "page_sha256", "row_count", "rows", "source_url"}
    nasdaq_required = {"payload_sha256", "row_count", "rows", "source_url"}
    if set(massive) != massive_required or set(nasdaq) != nasdaq_required:
        raise ProductionReleaseError("source cache provider fields are malformed")
    for field in ("source_url",):
        for provider in (massive, nasdaq):
            if not isinstance(provider[field], str) or not provider[field].startswith("https://"):
                raise ProductionReleaseError("source cache source_url must use HTTPS")
    for provider, ticker_field in ((massive, "ticker"), (nasdaq, "symbol")):
        rows = provider["rows"]
        if not isinstance(rows, list) or type(provider["row_count"]) is not int or provider["row_count"] != len(rows):
            raise ProductionReleaseError("source cache row_count does not match rows")
        indexed: dict[str, Mapping[str, object]] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise ProductionReleaseError("source cache rows must be objects")
            ticker = row.get(ticker_field)
            if not isinstance(ticker, str) or not ticker or ticker != ticker.strip().upper():
                raise ProductionReleaseError("source cache ticker is not canonical uppercase")
            if ticker in indexed:
                raise ProductionReleaseError(f"source cache contains duplicate ticker {ticker}")
            indexed[ticker] = row
        provider["_indexed"] = indexed
    if type(massive["page_count"]) is not int or massive["page_count"] <= 0:
        raise ProductionReleaseError("massive page_count must be positive")
    pages = massive["page_sha256"]
    if not isinstance(pages, list) or len(pages) != massive["page_count"]:
        raise ProductionReleaseError("massive page hashes do not match page_count")
    for item in pages:
        _canonical_hash(item, "massive page_sha256")
    _canonical_hash(nasdaq["payload_sha256"], "nasdaq payload_sha256")
    return SourceCache(
        path=source,
        sha256=_sha256_bytes(raw),
        fetched_at=_parse_utc_timestamp(payload["fetched_at"], "fetched_at"),
        massive_source_url=massive["source_url"],
        nasdaq_source_url=nasdaq["source_url"],
        massive_rows=massive["_indexed"],
        nasdaq_rows=nasdaq["_indexed"],
    )


def _identity_reason(massive: Mapping[str, object], nasdaq: Mapping[str, object]) -> str | None:
    if nasdaq.get("country") != "United States":
        return "foreign_issuer"
    if massive.get("type") != "CS":
        return "non_common_stock"
    if massive.get("locale") != "us" or massive.get("market") != "stocks":
        return "foreign_listing"
    if massive.get("currency_name") != "usd" or massive.get("active") is not True:
        return "inactive_or_non_usd"
    if massive.get("primary_exchange") not in _EXCHANGES:
        return "unsupported_exchange"
    return None


def _universe_rows(cache: SourceCache, price_rows: Sequence[Sequence[object]], signal_dt: date):
    bars: dict[str, list[tuple[date, Decimal, Decimal, Decimal, int]]] = {}
    for ticker, session, high, low, close, volume in price_rows:
        if type(session) is not date or session > signal_dt:
            raise ProductionReleaseError("production price query returned an invalid session")
        try:
            values = (Decimal(str(high)), Decimal(str(low)), Decimal(str(close)))
            volume_int = int(volume)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ProductionReleaseError("production price row is malformed") from exc
        if any(not value.is_finite() or value <= 0 for value in values) or volume_int < 0:
            raise ProductionReleaseError("production price row is malformed")
        bars.setdefault(str(ticker), []).append((session, values[0], values[1], values[2], volume_int))
    decisions: list[dict[str, object]] = []
    common = sorted(set(cache.massive_rows) & set(cache.nasdaq_rows))
    for ticker in common:
        massive, nasdaq = cache.massive_rows[ticker], cache.nasdaq_rows[ticker]
        identity_reason = _identity_reason(massive, nasdaq)
        sector = nasdaq.get("sector")
        if not isinstance(sector, str) or not sector.strip():
            sector = "Unknown"
        raw_cap = nasdaq.get("marketCap")
        try:
            market_cap = Decimal(str(raw_cap))
        except (InvalidOperation, ValueError, TypeError):
            market_cap = None
        ticker_bars = sorted(bars.get(ticker, []), key=lambda item: item[0])[-(MID_SMALL_PIVOT_POLICY.adv_sessions + 1) :]
        adv_bars = ticker_bars[-MID_SMALL_PIVOT_POLICY.adv_sessions :]
        reasons: list[str] = []
        if identity_reason:
            reasons.append(identity_reason)
        if market_cap is None or not market_cap.is_finite() or market_cap <= 0:
            reasons.append("missing_market_cap")
        elif market_cap < MID_SMALL_PIVOT_POLICY.market_cap_min:
            reasons.append("market_cap_below_minimum")
        elif market_cap > MID_SMALL_PIVOT_POLICY.market_cap_max:
            reasons.append("market_cap_above_maximum")
        if len(adv_bars) < MID_SMALL_PIVOT_POLICY.adv_sessions:
            reasons.append("insufficient_price_sessions")
        elif ticker_bars[-1][0] != signal_dt:
            reasons.append("missing_signal_date_price")
        close = ticker_bars[-1][3] if ticker_bars else None
        adv = None
        if len(adv_bars) == MID_SMALL_PIVOT_POLICY.adv_sessions:
            adv = sum((bar[3] * Decimal(bar[4]) for bar in adv_bars), Decimal(0)) / Decimal(len(adv_bars))
            if close is not None and close < MID_SMALL_PIVOT_POLICY.minimum_price:
                reasons.append("price_below_minimum")
            if adv < MID_SMALL_PIVOT_POLICY.minimum_average_dollar_volume:
                reasons.append("average_dollar_volume_below_minimum")
        reason_codes = tuple(sorted(set(reasons))) if reasons else ("eligible_mid_small_us_common_stock",)
        included = not reasons
        identity_id = f"bulk:{cache.sha256}:identity:{ticker}"
        cap_id = f"bulk:{cache.sha256}:market-cap:{ticker}" if market_cap is not None else None
        bar_ids = [f"wolfy:prices:{ticker}:{bar[0].isoformat()}" for bar in ticker_bars]
        evidence = {
            "source_cache_schema": SOURCE_CACHE_SCHEMA,
            "source_cache_sha256": cache.sha256,
            "identity": {
                "observation_id": identity_id,
                "security_type": "common_stock" if massive.get("type") == "CS" else str(massive.get("type")),
                "issuer_country": "US" if nasdaq.get("country") == "United States" else str(nasdaq.get("country")),
                "locale": massive.get("locale"),
                "market": massive.get("market"),
                "primary_exchange": _EXCHANGES.get(str(massive.get("primary_exchange")), str(massive.get("primary_exchange"))),
                "currency": str(massive.get("currency_name", "")).upper(),
                "active": massive.get("active"),
                "massive_source_url": cache.massive_source_url,
                "nasdaq_source_url": cache.nasdaq_source_url,
            },
            "market_cap": {
                "observation_id": cap_id,
                "value": str(market_cap) if market_cap is not None else None,
                "source_url": cache.nasdaq_source_url,
            },
            "bars": [
                {"observation_id": observation_id, "session": bar[0].isoformat(), "high": str(bar[1]), "low": str(bar[2]), "close": str(bar[3]), "volume": bar[4], "source": "local-wolfy-prices"}
                for observation_id, bar in zip(bar_ids, ticker_bars)
            ],
        }
        facts = {
            "ticker": ticker, "sector": sector, "included": included,
            "reasons": reason_codes, "source_evidence": evidence,
            "close": str(close) if close is not None else None,
            "adv": str(adv) if adv is not None else None,
        }
        decisions.append({
            "ticker": ticker, "sector": sector, "included": included,
            "reason_codes": reason_codes, "identity_observation_ids": (identity_id,),
            "risk_observation_ids": (), "denylist_observation_ids": (),
            "market_cap_observation_id": cap_id, "market_cap": market_cap,
            "bar_observation_ids": tuple(bar_ids), "close": close,
            "average_dollar_volume": adv, "source_evidence": evidence,
            "facts_hash": _json_hash(facts), "bars": ticker_bars,
        })
    if not decisions:
        raise ProductionReleaseError("source cache has no Massive/Nasdaq ticker intersection")
    return decisions


def _persist_bootstrap(conn, *, cache: SourceCache, signal_dt: date) -> tuple[str, str, uuid.UUID, int, int]:
    """Persist exact adapter-owned universe/run/gates/candidates in one transaction."""
    validate_production_connection(conn)
    tickers = sorted(set(cache.massive_rows) & set(cache.nasdaq_rows))
    price_rows = conn.execute(
        """SELECT ticker,dt,high,low,close,volume FROM (
               SELECT ticker,dt,high,low,close,volume,
                      row_number() OVER (PARTITION BY ticker ORDER BY dt DESC) AS rn
                 FROM prices WHERE ticker=ANY(%s) AND dt<=%s
             ) q WHERE rn<=%s ORDER BY ticker,dt""",
        (tickers, signal_dt, MID_SMALL_PIVOT_POLICY.adv_sessions + 1),
    ).fetchall()
    decisions = _universe_rows(cache, price_rows, signal_dt)
    decision_at = cache.fetched_at
    source_fingerprint = _json_hash({
        "signal_dt": signal_dt.isoformat(),
        "decision_at": decision_at.isoformat(),
        "policy_version": MID_SMALL_PIVOT_POLICY.version,
        "source_cache_sha256": cache.sha256,
        "members": [(row["ticker"], row["facts_hash"]) for row in decisions],
    })
    snapshot_id = str(uuid.uuid5(_UUID_NAMESPACE, source_fingerprint))
    included_count = sum(bool(row["included"]) for row in decisions)
    excluded_count = len(decisions) - included_count
    if included_count <= 0:
        raise ProductionReleaseError("deterministic recommendation universe is empty")
    conn.execute(
        """INSERT INTO recommendation_universe_snapshots(
               snapshot_id,signal_dt,decision_at,policy_version,source_fingerprint,included_count,excluded_count)
             VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (snapshot_id) DO NOTHING""",
        (snapshot_id, signal_dt, decision_at, MID_SMALL_PIVOT_POLICY.version, source_fingerprint, included_count, excluded_count),
    )
    for row in decisions:
        conn.execute(
            """INSERT INTO recommendation_universe_members(
                   snapshot_id,ticker,sector,included,reason_codes,identity_observation_ids,
                   risk_observation_ids,denylist_observation_ids,market_cap_observation_id,
                   market_cap,bar_observation_ids,close,average_dollar_volume,source_evidence,facts_hash)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                 ON CONFLICT (snapshot_id,ticker) DO NOTHING""",
            (snapshot_id, row["ticker"], row["sector"], row["included"], list(row["reason_codes"]),
             list(row["identity_observation_ids"]), [], [], row["market_cap_observation_id"], row["market_cap"],
             list(row["bar_observation_ids"]), row["close"], row["average_dollar_volume"],
             json.dumps(row["source_evidence"], sort_keys=True), row["facts_hash"]),
        )
    persisted = conn.execute(
        "SELECT count(*) FILTER (WHERE included),count(*) FILTER (WHERE NOT included) FROM recommendation_universe_members WHERE snapshot_id=%s",
        (snapshot_id,),
    ).fetchone()
    if persisted is None or tuple(persisted) != (included_count, excluded_count):
        raise ProductionReleaseError("persisted snapshot conflicts with deterministic source cache")

    identity_payload = {
        "evaluator_name": APPROVED_STRATEGY_ID,
        "evaluator_version": APPROVED_STRATEGY_VERSION,
        "target_session": signal_dt.isoformat(),
        "universe_snapshot_id": snapshot_id,
    }
    run_identity = _json_hash(identity_payload)
    run_id = uuid.uuid5(uuid.NAMESPACE_URL, f"wolfy:daily-evaluation:{run_identity}")
    stage_metadata = {
        "features": {
            "input_session": signal_dt.isoformat(),
            "computed_at": decision_at.isoformat(),
            "available_at": decision_at.isoformat(),
            "transformation_version": "production-prices-features-v1",
            "source_run_ids": [f"source-cache:{cache.sha256}"],
            "input_hash": cache.sha256,
            "universe_snapshot_id": snapshot_id,
            "provenance": {"source_cache_sha256": cache.sha256, "database": "wolfy"},
        }
    }
    conn.execute(
        """INSERT INTO daily_evaluation_runs(
               id,run_identity,target_session,evaluator_name,evaluator_version,
               universe_snapshot_id,required_stage_names,derived_stage_metadata,status)
             VALUES (%s,%s,%s,%s,%s,%s,ARRAY['features'],%s::jsonb,'started')
             ON CONFLICT (run_identity) DO NOTHING""",
        (run_id, run_identity, signal_dt, APPROVED_STRATEGY_ID, APPROVED_STRATEGY_VERSION,
         snapshot_id, json.dumps(stage_metadata, sort_keys=True)),
    )
    run_row = conn.execute(
        "SELECT id,status,universe_snapshot_id,derived_stage_metadata FROM daily_evaluation_runs WHERE run_identity=%s",
        (run_identity,),
    ).fetchone()
    if run_row is None or str(run_row[0]) != str(run_id) or run_row[2] != snapshot_id or run_row[3] != stage_metadata:
        raise ProductionReleaseError("daily run conflicts with deterministic bootstrap")

    feature_rows = conn.execute(
        "SELECT ticker,sma_fast,sma_slow,vol_ratio,atr FROM features WHERE dt=%s AND ticker=ANY(%s) ORDER BY ticker",
        (signal_dt, [row["ticker"] for row in decisions if row["included"]]),
    ).fetchall()
    features = {str(row[0]): row[1:] for row in feature_rows}
    spy_rows = conn.execute(
        "SELECT dt,close FROM prices WHERE ticker='SPY' AND dt<=%s ORDER BY dt DESC LIMIT 50",
        (signal_dt,),
    ).fetchall()
    if len(spy_rows) < 50 or spy_rows[0][0] != signal_dt:
        raise ProductionReleaseError("exact SPY 50-session production context is unavailable")
    spy_close = Decimal(str(spy_rows[0][1]))
    spy_sma = sum((Decimal(str(row[1])) for row in spy_rows), Decimal(0)) / Decimal(50)
    spy_lookback = Decimal(str(spy_rows[20][1])) if len(spy_rows) >= 21 else None
    if spy_lookback is None or spy_lookback <= 0:
        raise ProductionReleaseError("exact SPY return context is unavailable")
    spy_return = spy_close / spy_lookback - Decimal(1)

    from setup_evaluators import ApprovedBreakoutFacts, evaluate_approved_breakout
    candidate_count = 0
    gate_count = 0
    for member in decisions:
        if not member["included"]:
            continue
        ticker = str(member["ticker"])
        ticker_bars = member["bars"]
        current = ticker_bars[-1]
        prior = ticker_bars[-6:-1]
        lookback = ticker_bars[-21] if len(ticker_bars) >= 21 else None
        feature = features.get(ticker)
        result = None
        if feature is not None and len(prior) == 5 and lookback is not None and all(value is not None for value in feature):
            result = evaluate_approved_breakout(ApprovedBreakoutFacts(
                ticker=ticker, sector=str(member["sector"]), evaluated_at=decision_at,
                universe_eligible=True, close=current[3], high=current[1],
                prior_five_high=max(bar[1] for bar in prior), prior_five_low=min(bar[2] for bar in prior),
                sma_fast=feature[0], sma_slow=feature[1], volume_ratio=feature[2], atr=feature[3],
                ticker_return_20d=current[3] / lookback[3] - Decimal(1), spy_return_20d=spy_return,
                spy_close=spy_close, spy_sma_50=spy_sma, source_fingerprint=str(member["facts_hash"]),
                provenance={"source_cache_sha256": cache.sha256, "universe_snapshot_id": snapshot_id,
                            "prices": "local-wolfy", "features": "local-wolfy"},
                benchmark_context={"IWM": {"role": "context_only"}, "MDY": {"role": "context_only"}},
            ))
            evaluation = result.evaluation
            reason_codes = evaluation.reason_codes
            terminal_reason = evaluation.terminal_reason
            passed = evaluation.passed
            metrics = dict(evaluation.metrics)
            gate_facts = dict(evaluation.gate_facts)
            provenance = dict(evaluation.provenance)
            source_hash = evaluation.source_fingerprint
        else:
            passed = False
            reason_codes = ("missing_current_features",)
            terminal_reason = reason_codes[0]
            metrics = {}
            gate_facts = {"approved_rules_unchanged": True, "universe_eligible": True}
            provenance = {"source_cache_sha256": cache.sha256, "universe_snapshot_id": snapshot_id}
            source_hash = str(member["facts_hash"])
        gate_row = conn.execute(
            """INSERT INTO setup_gate_evaluations(
                   run_id,ticker,strategy,passed,reason_code_version,reason_codes,terminal_reason,
                   failed_gates,gate_facts,source_fingerprint,evaluated_at,metrics,provenance)
                 VALUES (%s,%s,%s,%s,2,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s::jsonb,%s::jsonb)
                 ON CONFLICT (run_id,ticker,strategy) DO NOTHING RETURNING id""",
            (run_id, ticker, APPROVED_STRATEGY_ID, passed, list(reason_codes), terminal_reason,
             json.dumps([] if passed else list(reason_codes)), json.dumps(gate_facts, sort_keys=True),
             source_hash, decision_at, json.dumps(metrics, sort_keys=True), json.dumps(provenance, sort_keys=True)),
        ).fetchone()
        if gate_row is None:
            gate_row = conn.execute(
                "SELECT id FROM setup_gate_evaluations WHERE run_id=%s AND ticker=%s AND strategy=%s",
                (run_id, ticker, APPROVED_STRATEGY_ID),
            ).fetchone()
        if gate_row is None:
            raise ProductionReleaseError("failed to persist deterministic gate evaluation")
        gate_count += 1
        if not passed or result is None:
            continue
        score_components = result.evaluation.score_components
        score = sum(score_components.values(), Decimal(0))
        candidate_id = uuid.uuid5(
            _CANDIDATE_NAMESPACE,
            f"{run_id}:{ticker}:{APPROVED_STRATEGY_ID}:{APPROVED_STRATEGY_VERSION}",
        )
        conn.execute(
            """INSERT INTO setup_candidates(
                   candidate_id,run_id,universe_snapshot_id,gate_evaluation_id,ticker,strategy_id,
                   strategy_version,sector,score,score_components,entry,stop,target,facts_hash)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)
                 ON CONFLICT (candidate_id) DO NOTHING""",
            (candidate_id, run_id, snapshot_id, gate_row[0], ticker, APPROVED_STRATEGY_ID,
             APPROVED_STRATEGY_VERSION, member["sector"], score,
             json.dumps({key: format(value, "f") for key, value in score_components.items()}, sort_keys=True),
             result.entry, result.stop, result.target, result.facts_hash),
        )
        candidate_count += 1
    if gate_count != included_count:
        raise ProductionReleaseError("gate coverage does not match included universe")
    stored_candidates = conn.execute(
        "SELECT count(*) FROM setup_candidates WHERE run_id=%s AND strategy_id=%s AND strategy_version=%s",
        (run_id, APPROVED_STRATEGY_ID, APPROVED_STRATEGY_VERSION),
    ).fetchone()[0]
    if stored_candidates != candidate_count:
        raise ProductionReleaseError("candidate persistence conflicts with deterministic bootstrap")

    if run_row[1] in ("started", "data_incomplete"):
        conn.execute("UPDATE daily_evaluation_runs SET status='evaluated' WHERE id=%s", (run_id,))
    elif run_row[1] not in ("evaluated", "published"):
        raise ProductionReleaseError("daily run is not publishable")
    return snapshot_id, source_fingerprint, run_id, included_count, candidate_count


def _release_payload(
    *, snapshot_id: str, snapshot_fingerprint: str, signal_dt: date,
    account_equity: Decimal, artifact_path: Path, evidence_path: str | Path | None,
    rollback_path: str | Path | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": RELEASE_SCHEMA, "enabled": True, "database": "wolfy",
        "config_version": CONFIG_VERSION, "strategy": APPROVED_STRATEGY,
        "strategy_id": APPROVED_STRATEGY_ID, "strategy_version": APPROVED_STRATEGY_VERSION,
        "policy_version": MID_SMALL_PIVOT_POLICY.version, "snapshot_id": snapshot_id,
        "snapshot_fingerprint": snapshot_fingerprint, "signal_dt": signal_dt.isoformat(),
        "publisher_count": 1, "account_equity": format(account_equity, "f"),
        "stock_fallback_enabled": True, "paper_only": True, "no_live_execution": True,
        "broker_execution_enabled": False, "external_delivery_enabled": False,
        "previous_publisher": "wolfy-approved-breakout-paper",
        "canary_evidence_path": str(evidence_path or artifact_path.with_suffix(".canary.json")),
        "rollback_state_path": str(rollback_path or artifact_path.with_suffix(".state.json")),
    }
    payload["scope_fingerprint"] = _scope_fingerprint(payload)
    return payload


def bootstrap_source_cache(
    source_cache_path: str | Path,
    *,
    artifact_path: str | Path = DEFAULT_RELEASE_ARTIFACT,
    signal_dt: date | None = None,
    account_equity: object = "100000",
    canary_evidence_path: str | Path | None = None,
    rollback_state_path: str | Path | None = None,
    conn=None,
) -> dict[str, object]:
    """Build and persist the exact production release from immutable source evidence."""
    cache = load_source_cache(source_cache_path)
    equity = _positive_decimal(account_equity, "account_equity")
    owns_connection = conn is None
    if owns_connection:
        import psycopg
        conn = psycopg.connect("dbname=wolfy user=root host=/var/run/postgresql")
    try:
        validate_production_connection(conn)
        target_session = signal_dt
        if target_session is None:
            row = conn.execute("SELECT max(dt) FROM prices WHERE dt < %s", (cache.fetched_at.date(),)).fetchone()
            target_session = row[0] if row else None
        if type(target_session) is not date:
            raise ProductionReleaseError("no completed production price session precedes source cache")
        snapshot_id, fingerprint, run_id, included, candidates = _persist_bootstrap(
            conn, cache=cache, signal_dt=target_session
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if owns_connection:
            conn.close()
    artifact = Path(artifact_path)
    payload = _release_payload(
        snapshot_id=snapshot_id, snapshot_fingerprint=fingerprint, signal_dt=target_session,
        account_equity=equity, artifact_path=artifact, evidence_path=canary_evidence_path,
        rollback_path=rollback_state_path,
    )
    _atomic_json(artifact, payload)
    load_release_artifact(artifact)
    return {
        "status": "bootstrapped", "artifact_path": str(artifact),
        "source_cache_sha256": cache.sha256, "signal_dt": target_session.isoformat(),
        "snapshot_id": snapshot_id, "snapshot_fingerprint": fingerprint,
        "daily_run_id": str(run_id), "included_count": included,
        "approved_breakout_candidates": candidates, "paper_only": True,
        "no_live_execution": True, "broker_orders_created": 0, "external_deliveries": 0,
    }


bootstrap_production_source_cache = bootstrap_source_cache


def _load_release_candidates(conn, release: ProductionRelease):
    """Load the exact approved-breakout candidate set from the bound snapshot."""
    from portfolio_allocator import PortfolioCandidate
    run = conn.execute(
        """SELECT id FROM daily_evaluation_runs
            WHERE target_session=%s AND universe_snapshot_id=%s
              AND evaluator_name=%s AND evaluator_version=%s
              AND status IN ('evaluated','published')
            ORDER BY created_at DESC,id DESC LIMIT 1""",
        (release.signal_dt, release.snapshot_id, release.strategy_id, release.strategy_version),
    ).fetchone()
    if run is None:
        raise ProductionReleaseError("real evaluated data for the exact snapshot is unavailable")
    rows = conn.execute(
        """SELECT c.candidate_id,c.universe_snapshot_id,c.ticker,c.strategy_id,
                  c.strategy_version,c.sector,c.score,c.entry,c.stop,c.target
             FROM setup_candidates c
             JOIN recommendation_universe_members m
               ON m.snapshot_id=c.universe_snapshot_id AND m.ticker=c.ticker
             JOIN setup_gate_evaluations g ON g.id=c.gate_evaluation_id AND g.run_id=c.run_id
            WHERE c.run_id=%s AND c.universe_snapshot_id=%s AND m.included AND g.passed
              AND c.strategy_id=%s AND c.strategy_version=%s AND g.strategy=%s
            ORDER BY c.score DESC,c.ticker,c.strategy_id""",
        (run[0], release.snapshot_id, release.strategy_id, release.strategy_version, release.strategy_id),
    ).fetchall()

    candidates = tuple(PortfolioCandidate(
        candidate_id=uuid.UUID(str(row[0])), universe_snapshot_id=uuid.UUID(str(row[1])),
        ticker=row[2], strategy_id=row[3], strategy_version=row[4], sector=row[5],
        score=row[6], entry=row[7], stop=row[8], target=row[9],
    ) for row in rows)
    return uuid.UUID(str(run[0])), candidates


def _publish_production_once(conn, release: ProductionRelease) -> int:
    from instrument_decision import decide_instrument
    from orchestration_runner import load_mid_small_existing_positions
    from portfolio_allocator import allocate_portfolio
    from recommendation_writer import PivotInstrumentRecommendation, ProductionPaperScope, write_pivot_instrument_recommendations
    run_id, candidates = _load_release_candidates(conn, release)
    if not candidates:
        return 0
    allocation = allocate_portfolio(candidates, existing_positions=load_mid_small_existing_positions(conn))
    if not allocation.selected:
        return 0
    recommendations = tuple(PivotInstrumentRecommendation(
        run_id=run_id, allocation=selected,
        instrument=decide_instrument(selected.candidate, decision_at=datetime.now(timezone.utc),
                                     account_equity=release.account_equity, chain_snapshot=None),
        option_evaluation_id=None,
    ) for selected in allocation.selected)
    scope = ProductionPaperScope(
        scope_fingerprint=release.scope_fingerprint, snapshot_id=uuid.UUID(release.snapshot_id),
        strategy_id=release.strategy_id, strategy_version=release.strategy_version,
    )
    result = write_pivot_instrument_recommendations(
        conn, recommendations=recommendations, signal_dt=release.signal_dt,
        dry_run=False, production_scope=scope,
    )
    if result.broker_orders_created != 0:
        raise ProductionReleaseError("broker_orders_created invariant failed")
    return result.inserted


def _production_readback(conn, release: ProductionRelease) -> dict[str, object]:
    scoped = conn.execute(
        """SELECT r.id::text,r.ticker,r.notes,
                  EXISTS (SELECT 1 FROM paper_trades pt WHERE pt.recommendation_id=r.id::text)
             FROM recommendations r
            WHERE r.notes->>'production_release_scope'=%s
              AND r.notes->>'universe_snapshot_id'=%s
              AND r.notes->>'strategy_name'=%s ORDER BY r.id""",
        (release.scope_fingerprint, release.snapshot_id, release.strategy_id),
    ).fetchall()
    active = conn.execute(
        """SELECT DISTINCT ON (r.ticker) r.ticker,r.notes
             FROM recommendations r
            WHERE r.status IN ('paper_candidate','paper_logged')
              AND r.notes->>'paper_only'='true' AND r.notes->>'no_live_execution'='true'
            ORDER BY r.ticker,r.id DESC"""
    ).fetchall()
    sectors: dict[str, int] = {}
    risks: list[str] = []
    for _ticker, raw_notes in active:
        notes = raw_notes if isinstance(raw_notes, Mapping) else {}
        sector = str(notes.get("sector") or "Unknown")
        sectors[sector] = sectors.get(sector, 0) + 1
        risks.append(str(notes.get("risk_fraction") or "0.05"))
    ids = [row[0] for row in scoped]
    scoped_safe = all(
        isinstance(row[2], Mapping) and row[2].get("paper_only") is True
        and row[2].get("no_live_execution") is True
        and row[2].get("broker_order_submitted") is False
        and row[2].get("strategy_name") == release.strategy_id
        and row[2].get("strategy_version") == release.strategy_version
        and row[2].get("risk_fraction") == "0.05"
        and row[2].get("instrument_expression") in {"long_call", "call_debit_spread", "underlying_stock_fallback"}
        and (row[2].get("instrument_expression") != "underlying_stock_fallback" or bool(row[2].get("fallback_reasons")))
        and row[3] is True for row in scoped
    )
    return {
        "recommendation_ids": ids, "recommendations_created": 0,
        "decision": "actionable" if ids else "no_trade",
        "positions_total": len(active), "maximum_sector_positions": max(sectors.values(), default=0),
        "risk_fractions": risks,
        "aggregate_risk": str(sum((Decimal(value) for value in risks), Decimal("0"))),
        "research_only_published": 0 if scoped_safe else 1,
        "exact_chain_or_stock_fallback": scoped_safe, "paper_only": True,
        "no_live_execution": True, "broker_orders_created": 0, "external_deliveries": 0,
    }


def run_production_canary(
    artifact_path: str | Path = DEFAULT_RELEASE_ARTIFACT, *, scheduled: bool = False
) -> dict[str, object]:
    """Run the real bounded production-paper adapter against exact DB ``wolfy``."""
    import psycopg
    release = load_release_artifact(artifact_path)
    scheduled_evidence: Mapping[str, object] | None = None
    if scheduled:
        authorize_scheduled_production(release, artifact_path)
        scheduled_evidence = _load_json_object(release.canary_evidence_path, "canary evidence")
    with psycopg.connect("dbname=wolfy user=root host=/var/run/postgresql") as conn:
        validate_production_connection(conn)
        verify_snapshot_preflight(conn, release)
        conn.commit()
        def publish(*, rerun: bool) -> Mapping[str, object]:
            try:
                created = _publish_production_once(conn, release)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            payload = _production_readback(conn, release)
            conn.commit()
            payload["recommendations_created"] = created
            return payload
        def readback() -> Mapping[str, object]:
            payload = _production_readback(conn, release)
            conn.commit()
            return payload
        if scheduled:
            if scheduled_evidence is None:  # defensive; authorization above must populate it
                raise ProductionReleaseError("scheduled canary evidence is unavailable")
            evidence = execute_scheduled_callbacks(
                release,
                publish=publish,
                readback=readback,
                canary_evidence=scheduled_evidence,
            )
        else:
            evidence = execute_canary_callbacks(release, publish=publish, readback=readback)
    if not scheduled:
        evidence = persist_canary_evidence(release, artifact_path, evidence)
    return evidence
