"""Typed, transactional persistence for auditable daily setup evaluation runs.

Ledger text is canonical when nonempty and unchanged by stripping ASCII C0
controls, ordinary space, and DEL from both edges. Unicode whitespace is not
implicitly normalized, keeping the Python and PostgreSQL contract byte-clear.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal, Mapping

RunStatus = Literal["started", "data_incomplete", "evaluated", "published", "failed"]

_RUN_STATUSES = frozenset(
    {"started", "data_incomplete", "evaluated", "published", "failed"}
)
_RUN_TRANSITIONS = {
    "started": frozenset({"data_incomplete", "evaluated", "failed"}),
    "data_incomplete": frozenset({"evaluated", "failed"}),
    "evaluated": frozenset({"published", "failed"}),
    "published": frozenset(),
    "failed": frozenset(),
}
_ASCII_LEDGER_EDGE_CHARS = "".join(chr(codepoint) for codepoint in range(33)) + "\x7f"


class InvalidRunTransition(ValueError):
    """Raised when a run status would move along an undeclared edge."""


class LedgerValidationError(ValueError):
    """Raised before any write when ledger input is non-canonical."""


@dataclass(frozen=True)
class DailyRunIdentity:
    target_session: date
    evaluator_name: str
    evaluator_version: str
    universe_snapshot_id: str
    required_stages: tuple[str, ...] = ("features",)


@dataclass(frozen=True)
class DailyRun:
    run_id: uuid.UUID
    status: RunStatus


@dataclass(frozen=True)
class IngestionManifest:
    dataset: str
    target_session: date
    provider: str
    source_endpoint: str
    entitlement_class: str
    delay_class: str
    started_at: datetime
    completed_at: datetime | None
    expected_symbol_count: int
    received_symbol_count: int
    expected_row_count: int
    received_row_count: int
    retry_count: int
    status: str
    raw_payload_sha256: str | None
    immutable_object_ref: str | None
    parser_version: str
    schema_version: str
    quality_gate: str
    provenance: Mapping[str, Any]


CANONICAL_REASON_CODES: Mapping[int, frozenset[str]] = {
    1: frozenset(
        {
            "passed",
            "missing_current_price",
            "missing_current_features",
            "insufficient_history",
            "security_ineligible",
            "liquidity_failed",
            "market_regime_failed",
            "trend_failed",
            "breakout_not_confirmed",
            "pullback_shape_failed",
            "relative_strength_failed",
            "volume_failed",
            "stop_risk_too_wide",
            "overextended",
            "breadth_unavailable",
            "breadth_failed",
            "sector_confirmation_failed",
            "event_landmine",
            "option_chain_missing",
            "option_liquidity_failed",
            "portfolio_correlation_block",
            "daily_limit_block",
        }
    )
}


@dataclass(frozen=True)
class GateEvaluation:
    ticker: str
    strategy: str
    passed: bool
    reason_code_version: int
    reason_codes: tuple[str, ...]
    terminal_reason: str
    evaluated_at: datetime
    metrics: Mapping[str, Any]
    gate_facts: Mapping[str, Any]
    source_fingerprint: str
    provenance: Mapping[str, Any]


@dataclass(frozen=True)
class DerivedStageMetadata:
    stage_name: str
    input_session: date
    computed_at: datetime
    available_at: datetime
    transformation_version: str
    source_run_ids: tuple[str, ...]
    input_hash: str
    universe_snapshot_id: str
    provenance: Mapping[str, Any]


def _identity_key(identity: DailyRunIdentity) -> str:
    payload = json.dumps(
        {
            "evaluator_name": identity.evaluator_name,
            "evaluator_version": identity.evaluator_version,
            "target_session": identity.target_session.isoformat(),
            "universe_snapshot_id": identity.universe_snapshot_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def create_daily_run(conn, identity: DailyRunIdentity) -> DailyRun:
    """Create or return the uniquely identified daily run."""
    if type(identity.target_session) is not date:
        raise LedgerValidationError("target_session must be a date")
    if any(
        not _is_canonical_string(value)
        for value in (
            identity.evaluator_name,
            identity.evaluator_version,
            identity.universe_snapshot_id,
        )
    ):
        raise LedgerValidationError("run identity strings must be non-empty and canonical")
    if (
        not identity.required_stages
        or any(not _is_canonical_string(stage) for stage in identity.required_stages)
        or tuple(sorted(set(identity.required_stages))) != identity.required_stages
    ):
        raise LedgerValidationError(
            "required_stages must be non-empty, unique, and sorted"
        )
    key = _identity_key(identity)
    run_id = uuid.uuid5(uuid.NAMESPACE_URL, f"wolfy:daily-evaluation:{key}")
    row = conn.execute(
        """
        INSERT INTO daily_evaluation_runs(
            id, run_identity, target_session, evaluator_name,
            evaluator_version, universe_snapshot_id, required_stage_names
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (run_identity) DO NOTHING
        RETURNING id, status, required_stage_names
        """,
        (
            run_id,
            key,
            identity.target_session,
            identity.evaluator_name,
            identity.evaluator_version,
            identity.universe_snapshot_id,
            list(identity.required_stages),
        ),
    ).fetchone()
    if row is None:
        row = conn.execute(
            """
            SELECT id, status, required_stage_names
            FROM daily_evaluation_runs WHERE run_identity=%s
            """,
            (key,),
        ).fetchone()
    if tuple(row[2]) != identity.required_stages:
        raise LedgerValidationError(
            "rerun required_stages differ from immutable run identity"
        )
    return DailyRun(run_id=row[0], status=row[1])


def transition_daily_run(conn, run_id: uuid.UUID, status: RunStatus) -> DailyRun:
    """Lock and transition a run, rejecting unknown and reverse states."""
    if status not in _RUN_STATUSES:
        raise InvalidRunTransition(f"unknown daily run status: {status!r}")
    row = conn.execute(
        "SELECT status FROM daily_evaluation_runs WHERE id=%s FOR UPDATE", (run_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"daily evaluation run not found: {run_id}")
    current = row[0]
    if status == current:
        return DailyRun(run_id=run_id, status=current)
    if status not in _RUN_TRANSITIONS[current]:
        raise InvalidRunTransition(
            f"invalid daily run transition: {current} -> {status}"
        )
    if status == "published":
        _validate_publishable(conn, run_id)
    updated = conn.execute(
        "UPDATE daily_evaluation_runs SET status=%s WHERE id=%s RETURNING status",
        (status, run_id),
    ).fetchone()
    return DailyRun(run_id=run_id, status=updated[0])


def _require_utc(value: datetime | None, field: str) -> None:
    if value is not None and (
        value.tzinfo is None or value.utcoffset() != timedelta(0)
    ):
        raise LedgerValidationError(f"{field} must be UTC-aware")


def _is_canonical_string(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip(_ASCII_LEDGER_EDGE_CHARS)
    )


def _validate_json_mapping(value: object, field: str) -> None:
    if not isinstance(value, Mapping):
        raise LedgerValidationError(f"{field} must be a JSON object")
    try:
        json.dumps(
            dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise LedgerValidationError(f"{field} must contain JSON values") from exc


def _validate_manifest(manifest: IngestionManifest) -> None:
    for field in (
        "dataset",
        "provider",
        "source_endpoint",
        "entitlement_class",
        "delay_class",
        "parser_version",
        "schema_version",
    ):
        if not _is_canonical_string(getattr(manifest, field)):
            raise LedgerValidationError(f"{field} must be a non-empty canonical string")
    if type(manifest.target_session) is not date:
        raise LedgerValidationError("target_session must be a date")
    _require_utc(manifest.started_at, "started_at")
    _require_utc(manifest.completed_at, "completed_at")
    counts = (
        manifest.expected_symbol_count,
        manifest.received_symbol_count,
        manifest.expected_row_count,
        manifest.received_row_count,
        manifest.retry_count,
    )
    if any(type(value) is not int or value < 0 for value in counts):
        raise LedgerValidationError(
            "manifest counts and retry_count must be non-negative integers"
        )
    if manifest.status not in {"started", "completed", "data_incomplete", "failed"}:
        raise LedgerValidationError(f"unknown manifest status: {manifest.status!r}")
    if manifest.quality_gate not in {"not_run", "passed", "failed"}:
        raise LedgerValidationError(f"unknown quality gate: {manifest.quality_gate!r}")
    if manifest.status == "completed" and manifest.completed_at is None:
        raise LedgerValidationError("completed manifest requires completed_at")
    if manifest.completed_at is not None and manifest.completed_at < manifest.started_at:
        raise LedgerValidationError("completed_at must not precede started_at")
    if (manifest.raw_payload_sha256 is None) == (manifest.immutable_object_ref is None):
        raise LedgerValidationError(
            "exactly one raw payload hash or immutable object ref is required"
        )
    if manifest.raw_payload_sha256 is not None and not re.fullmatch(
        r"[0-9a-f]{64}", manifest.raw_payload_sha256
    ):
        raise LedgerValidationError(
            "raw_payload_sha256 must be canonical lowercase SHA-256"
        )
    if manifest.immutable_object_ref is not None and not _is_canonical_string(
        manifest.immutable_object_ref
    ):
        raise LedgerValidationError("immutable_object_ref must be non-empty and canonical")
    _validate_json_mapping(manifest.provenance, "provenance")


def _lock_mutable_run(conn, run_id: uuid.UUID) -> None:
    row = conn.execute(
        "SELECT status FROM daily_evaluation_runs WHERE id=%s FOR UPDATE", (run_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"daily evaluation run not found: {run_id}")
    if row[0] == "published":
        raise LedgerValidationError("published daily evaluation run is immutable")


def upsert_ingestion_manifest(
    conn, run_id: uuid.UUID, manifest: IngestionManifest
) -> int:
    """Validate and deterministically upsert one source manifest per run."""
    from psycopg.types.json import Jsonb

    _validate_manifest(manifest)
    _lock_mutable_run(conn, run_id)
    row = conn.execute(
        """
        INSERT INTO ingestion_run_manifests(
            run_id,dataset,target_session,provider,source_endpoint,
            entitlement_class,delay_class,started_at,completed_at,
            expected_symbol_count,received_symbol_count,expected_row_count,
            received_row_count,retry_count,status,raw_payload_sha256,
            immutable_object_ref,parser_version,schema_version,quality_gate,provenance
        ) VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
        )
        ON CONFLICT (run_id,dataset,provider,source_endpoint) DO UPDATE SET
            target_session=EXCLUDED.target_session,
            entitlement_class=EXCLUDED.entitlement_class,
            delay_class=EXCLUDED.delay_class,
            started_at=EXCLUDED.started_at,
            completed_at=EXCLUDED.completed_at,
            expected_symbol_count=EXCLUDED.expected_symbol_count,
            received_symbol_count=EXCLUDED.received_symbol_count,
            expected_row_count=EXCLUDED.expected_row_count,
            received_row_count=EXCLUDED.received_row_count,
            retry_count=EXCLUDED.retry_count,
            status=EXCLUDED.status,
            raw_payload_sha256=EXCLUDED.raw_payload_sha256,
            immutable_object_ref=EXCLUDED.immutable_object_ref,
            parser_version=EXCLUDED.parser_version,
            schema_version=EXCLUDED.schema_version,
            quality_gate=EXCLUDED.quality_gate,
            provenance=EXCLUDED.provenance,
            updated_at=now()
        RETURNING id
        """,
        (
            run_id,
            manifest.dataset,
            manifest.target_session,
            manifest.provider,
            manifest.source_endpoint,
            manifest.entitlement_class,
            manifest.delay_class,
            manifest.started_at,
            manifest.completed_at,
            manifest.expected_symbol_count,
            manifest.received_symbol_count,
            manifest.expected_row_count,
            manifest.received_row_count,
            manifest.retry_count,
            manifest.status,
            manifest.raw_payload_sha256,
            manifest.immutable_object_ref,
            manifest.parser_version,
            manifest.schema_version,
            manifest.quality_gate,
            Jsonb(dict(manifest.provenance)),
        ),
    ).fetchone()
    return int(row[0])


def _validate_gate(evaluation: GateEvaluation) -> None:
    if not _is_canonical_string(evaluation.ticker) or (
        evaluation.ticker != evaluation.ticker.upper()
    ):
        raise LedgerValidationError("ticker must be non-empty canonical uppercase")
    if not _is_canonical_string(evaluation.strategy):
        raise LedgerValidationError("strategy must be a non-empty canonical string")
    if type(evaluation.passed) is not bool:
        raise LedgerValidationError("passed must be a boolean")
    allowed = CANONICAL_REASON_CODES.get(evaluation.reason_code_version)
    if allowed is None:
        raise LedgerValidationError(
            f"unknown reason code version: {evaluation.reason_code_version!r}"
        )
    if (
        not evaluation.reason_codes
        or tuple(sorted(set(evaluation.reason_codes))) != evaluation.reason_codes
        or not set(evaluation.reason_codes).issubset(allowed)
    ):
        raise LedgerValidationError("reason_codes must be known, unique, and sorted")
    if evaluation.passed != (evaluation.reason_codes == ("passed",)) or (
        not evaluation.passed and "passed" in evaluation.reason_codes
    ):
        raise LedgerValidationError("passed and reason_codes are inconsistent")
    if evaluation.terminal_reason not in evaluation.reason_codes:
        raise LedgerValidationError("terminal_reason must designate a recorded reason")
    if evaluation.passed and evaluation.terminal_reason != "passed":
        raise LedgerValidationError("a passed gate requires terminal_reason='passed'")
    _require_utc(evaluation.evaluated_at, "evaluated_at")
    _validate_json_mapping(evaluation.metrics, "metrics")
    _validate_json_mapping(evaluation.gate_facts, "gate_facts")
    if not _is_canonical_string(evaluation.source_fingerprint):
        raise LedgerValidationError("source_fingerprint must be non-empty and canonical")
    _validate_json_mapping(evaluation.provenance, "provenance")


def upsert_gate_evaluation(conn, run_id: uuid.UUID, evaluation: GateEvaluation) -> int:
    """Validate and upsert exactly one gate decision per run/ticker/strategy."""
    from psycopg.types.json import Jsonb

    _validate_gate(evaluation)
    _lock_mutable_run(conn, run_id)
    row = conn.execute(
        """
        INSERT INTO setup_gate_evaluations(
            run_id,ticker,strategy,passed,reason_code_version,reason_codes,
            terminal_reason,failed_gates,gate_facts,source_fingerprint,
            evaluated_at,metrics,provenance
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (run_id,ticker,strategy) DO UPDATE SET
            passed=EXCLUDED.passed,
            reason_code_version=EXCLUDED.reason_code_version,
            reason_codes=EXCLUDED.reason_codes,
            terminal_reason=EXCLUDED.terminal_reason,
            failed_gates=EXCLUDED.failed_gates,
            gate_facts=EXCLUDED.gate_facts,
            source_fingerprint=EXCLUDED.source_fingerprint,
            evaluated_at=EXCLUDED.evaluated_at,
            metrics=EXCLUDED.metrics,
            provenance=EXCLUDED.provenance,
            updated_at=now()
        RETURNING id
        """,
        (
            run_id,
            evaluation.ticker,
            evaluation.strategy,
            evaluation.passed,
            evaluation.reason_code_version,
            list(evaluation.reason_codes),
            evaluation.terminal_reason,
            Jsonb([] if evaluation.passed else list(evaluation.reason_codes)),
            Jsonb(dict(evaluation.gate_facts)),
            evaluation.source_fingerprint,
            evaluation.evaluated_at,
            Jsonb(dict(evaluation.metrics)),
            Jsonb(dict(evaluation.provenance)),
        ),
    ).fetchone()
    return int(row[0])


def _validate_derived_stage(metadata: DerivedStageMetadata) -> None:
    for field in ("stage_name", "transformation_version", "universe_snapshot_id"):
        if not _is_canonical_string(getattr(metadata, field)):
            raise LedgerValidationError(f"{field} must be a non-empty canonical string")
    if type(metadata.input_session) is not date:
        raise LedgerValidationError("input_session must be a date")
    if not isinstance(metadata.computed_at, datetime) or not isinstance(
        metadata.available_at, datetime
    ):
        raise LedgerValidationError("computed_at and available_at must be datetimes")
    _require_utc(metadata.computed_at, "computed_at")
    _require_utc(metadata.available_at, "available_at")
    if metadata.available_at < metadata.computed_at:
        raise LedgerValidationError("available_at must not precede computed_at")
    if (
        not isinstance(metadata.source_run_ids, tuple)
        or not metadata.source_run_ids
        or any(not _is_canonical_string(value) for value in metadata.source_run_ids)
        or len(set(metadata.source_run_ids)) != len(metadata.source_run_ids)
        or metadata.source_run_ids != tuple(sorted(metadata.source_run_ids))
    ):
        raise LedgerValidationError(
            "source_run_ids must be non-empty, sorted, unique canonical strings"
        )
    if not isinstance(metadata.input_hash, str) or not re.fullmatch(
        r"[0-9a-f]{64}", metadata.input_hash
    ):
        raise LedgerValidationError("input_hash must be canonical lowercase SHA-256")
    _validate_json_mapping(metadata.provenance, "provenance")


def record_derived_stage_metadata(
    conn, run_id: uuid.UUID, metadata: DerivedStageMetadata
) -> None:
    """Lock a run and idempotently replace one required derived-stage record."""
    from psycopg.types.json import Jsonb

    _validate_derived_stage(metadata)
    run = conn.execute(
        """
        SELECT target_session, universe_snapshot_id, required_stage_names, status
        FROM daily_evaluation_runs WHERE id=%s FOR UPDATE
        """,
        (run_id,),
    ).fetchone()
    if run is None:
        raise LookupError(f"daily evaluation run not found: {run_id}")
    target_session, universe_snapshot_id, required_stage_names, status = run
    if status == "published":
        raise LedgerValidationError("published daily evaluation run is immutable")
    if metadata.stage_name not in required_stage_names:
        raise LedgerValidationError("stage_name is not required by the immutable run")
    if metadata.universe_snapshot_id != universe_snapshot_id:
        raise LedgerValidationError(
            "derived stage universe_snapshot_id differs from immutable run"
        )
    if metadata.input_session != target_session:
        raise LedgerValidationError(
            "derived stage input_session differs from target session"
        )
    payload = {
        "input_session": metadata.input_session.isoformat(),
        "computed_at": metadata.computed_at.isoformat(),
        "available_at": metadata.available_at.isoformat(),
        "transformation_version": metadata.transformation_version,
        "source_run_ids": list(metadata.source_run_ids),
        "input_hash": metadata.input_hash,
        "universe_snapshot_id": metadata.universe_snapshot_id,
        "provenance": dict(metadata.provenance),
    }
    conn.execute(
        """
        UPDATE daily_evaluation_runs
        SET derived_stage_metadata =
                jsonb_set(derived_stage_metadata, ARRAY[%s], %s, true),
            updated_at = now()
        WHERE id=%s
        """,
        (metadata.stage_name, Jsonb(payload), run_id),
    )


def _parse_utc_stage_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise LedgerValidationError(f"derived stage {field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise LedgerValidationError(
            f"derived stage {field} must be an ISO timestamp"
        ) from exc
    _require_utc(parsed, f"derived stage {field}")
    return parsed


def _validate_stored_stage(
    stage_name: str,
    value: object,
    *,
    target_session: date,
    universe_snapshot_id: str,
) -> None:
    if not _is_canonical_string(stage_name) or not isinstance(value, Mapping):
        raise LedgerValidationError(f"derived stage {stage_name!r} is not canonical")
    required = {
        "input_session",
        "computed_at",
        "available_at",
        "transformation_version",
        "source_run_ids",
        "input_hash",
        "universe_snapshot_id",
        "provenance",
    }
    if set(value) != required:
        raise LedgerValidationError(
            f"derived stage {stage_name!r} has incomplete metadata"
        )
    if value["input_session"] != target_session.isoformat():
        raise LedgerValidationError(
            f"derived stage {stage_name!r} has wrong input session"
        )
    computed_at = _parse_utc_stage_timestamp(value["computed_at"], "computed_at")
    available_at = _parse_utc_stage_timestamp(value["available_at"], "available_at")
    if available_at < computed_at:
        raise LedgerValidationError(
            f"derived stage {stage_name!r} available_at precedes computed_at"
        )
    for field in ("transformation_version", "universe_snapshot_id"):
        if not _is_canonical_string(value[field]):
            raise LedgerValidationError(
                f"derived stage {stage_name!r} has invalid {field}"
            )
    source_run_ids = value["source_run_ids"]
    if (
        not isinstance(source_run_ids, list)
        or not source_run_ids
        or any(not _is_canonical_string(item) for item in source_run_ids)
        or len(set(source_run_ids)) != len(source_run_ids)
    ):
        raise LedgerValidationError(
            f"derived stage {stage_name!r} has invalid source_run_ids"
        )
    if not isinstance(value["input_hash"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", value["input_hash"]
    ):
        raise LedgerValidationError(
            f"derived stage {stage_name!r} has invalid input_hash"
        )
    if value["universe_snapshot_id"] != universe_snapshot_id:
        raise LedgerValidationError(
            f"derived stage {stage_name!r} has wrong universe snapshot"
        )
    _validate_json_mapping(value["provenance"], "derived stage provenance")


def _validate_publishable(conn, run_id: uuid.UUID) -> None:
    run = conn.execute(
        """
        SELECT target_session, universe_snapshot_id,
               required_stage_names, derived_stage_metadata
        FROM daily_evaluation_runs WHERE id=%s
        """,
        (run_id,),
    ).fetchone()
    if run is None:
        raise LookupError(f"daily evaluation run not found: {run_id}")
    target_session, universe_snapshot_id, required_stage_names, stage_metadata = run
    manifest_ready = conn.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM ingestion_run_manifests
            WHERE run_id=%s
              AND target_session=%s
              AND status='completed'
              AND completed_at IS NOT NULL
              AND quality_gate='passed'
              AND expected_symbol_count=received_symbol_count
              AND expected_row_count=received_row_count
        )
        """,
        (run_id, target_session),
    ).fetchone()[0]
    if not manifest_ready:
        raise LedgerValidationError(
            "published run requires a complete passed ingestion manifest for target session"
        )
    if (
        not required_stage_names
        or tuple(sorted(set(required_stage_names))) != tuple(required_stage_names)
        or any(not _is_canonical_string(name) for name in required_stage_names)
        or not isinstance(stage_metadata, Mapping)
    ):
        raise LedgerValidationError("published run has invalid required derived stages")
    for stage_name in required_stage_names:
        if stage_name not in stage_metadata:
            raise LedgerValidationError(
                f"published run missing derived stage: {stage_name}"
            )
        _validate_stored_stage(
            stage_name,
            stage_metadata[stage_name],
            target_session=target_session,
            universe_snapshot_id=universe_snapshot_id,
        )
