"""Common, fail-closed setup evaluation and allocator-candidate contracts."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from daily_evaluation_ledger import CANONICAL_REASON_CODES

_CANDIDATE_NAMESPACE = uuid.UUID("97823487-9278-492d-83cd-957102c2cb29")
_HASH = re.compile(r"[0-9a-f]{64}")
_ASCII_EDGE = "".join(chr(codepoint) for codepoint in range(33)) + "\x7f"


class SetupContractError(ValueError):
    """Raised before writes when a setup evaluation or candidate is unsafe."""


def _text(value: object, field: str, *, uppercase: bool = False) -> str:
    if not isinstance(value, str) or not value or value != value.strip(_ASCII_EDGE):
        raise SetupContractError(f"{field} must be non-empty canonical text")
    if uppercase and value != value.upper():
        raise SetupContractError(f"{field} must be uppercase")
    return value


def _uuid(value: object, field: str) -> uuid.UUID:
    if not isinstance(value, uuid.UUID):
        raise SetupContractError(f"{field} must be a UUID")
    return value


def _decimal(value: object, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise SetupContractError(f"{field} must be a finite decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SetupContractError(f"{field} must be a finite decimal") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise SetupContractError(f"{field} must be a finite{' positive' if positive else ''} decimal")
    return result


def _json_mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SetupContractError(f"{field} must be a JSON object")
    result = dict(value)
    if any(not isinstance(key, str) for key in result):
        raise SetupContractError(f"{field} keys must be strings")
    try:
        json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SetupContractError(f"{field} must contain finite JSON values") from exc
    return result


def _score_components(value: object) -> dict[str, Decimal]:
    if not isinstance(value, Mapping) or not value:
        raise SetupContractError("score_components must be a non-empty object")
    normalized: dict[str, Decimal] = {}
    for key, component in value.items():
        canonical_key = _text(key, "score component name")
        normalized[canonical_key] = _decimal(component, f"score component {canonical_key}")
    if len(normalized) != len(value):
        raise SetupContractError("score component names must be unique")
    return dict(sorted(normalized.items()))


@dataclass(frozen=True, slots=True)
class SetupEvaluation:
    ticker: str
    strategy_id: str
    strategy_version: str
    sector: str
    passed: bool
    reason_code_version: int
    reason_codes: tuple[str, ...]
    terminal_reason: str
    evaluated_at: datetime
    metrics: Mapping[str, Any]
    gate_facts: Mapping[str, Any]
    source_fingerprint: str
    provenance: Mapping[str, Any]
    score_components: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        _text(self.ticker, "ticker", uppercase=True)
        _text(self.strategy_id, "strategy_id")
        _text(self.strategy_version, "strategy_version")
        _text(self.sector, "sector")
        if type(self.passed) is not bool:
            raise SetupContractError("passed must be boolean")
        allowed = CANONICAL_REASON_CODES.get(self.reason_code_version)
        if allowed is None:
            raise SetupContractError("unknown reason code version")
        if (
            not isinstance(self.reason_codes, tuple)
            or not self.reason_codes
            or self.reason_codes != tuple(sorted(set(self.reason_codes)))
            or not set(self.reason_codes).issubset(allowed)
        ):
            raise SetupContractError("reason_codes must be known, sorted, and unique")
        if self.passed != (self.reason_codes == ("passed",)):
            raise SetupContractError("passed and reason_codes are inconsistent")
        if self.terminal_reason not in self.reason_codes:
            raise SetupContractError("terminal_reason must be recorded")
        if not isinstance(self.evaluated_at, datetime) or self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise SetupContractError("evaluated_at must be timezone-aware")
        object.__setattr__(self, "metrics", _json_mapping(self.metrics, "metrics"))
        object.__setattr__(self, "gate_facts", _json_mapping(self.gate_facts, "gate_facts"))
        if not isinstance(self.source_fingerprint, str) or not _HASH.fullmatch(self.source_fingerprint):
            raise SetupContractError("source_fingerprint must be lowercase SHA-256")
        object.__setattr__(self, "provenance", _json_mapping(self.provenance, "provenance"))
        object.__setattr__(self, "score_components", _score_components(self.score_components))


@dataclass(frozen=True, slots=True)
class SetupCandidate:
    run_id: uuid.UUID
    universe_snapshot_id: uuid.UUID
    gate_evaluation_id: int
    ticker: str
    strategy_id: str
    strategy_version: str
    sector: str
    score: Decimal
    score_components: Mapping[str, Decimal]
    entry: Decimal
    stop: Decimal
    target: Decimal
    facts_hash: str

    def __post_init__(self) -> None:
        _uuid(self.run_id, "run_id")
        _uuid(self.universe_snapshot_id, "universe_snapshot_id")
        if type(self.gate_evaluation_id) is not int or self.gate_evaluation_id <= 0:
            raise SetupContractError("gate_evaluation_id must be a positive integer")
        _text(self.ticker, "ticker", uppercase=True)
        _text(self.strategy_id, "strategy_id")
        _text(self.strategy_version, "strategy_version")
        _text(self.sector, "sector")
        score = _decimal(self.score, "score")
        components = _score_components(self.score_components)
        entry = _decimal(self.entry, "entry", positive=True)
        stop = _decimal(self.stop, "stop", positive=True)
        target = _decimal(self.target, "target", positive=True)
        if score != sum(components.values(), Decimal(0)):
            raise SetupContractError("score must equal the deterministic score component sum")
        if stop >= entry:
            raise SetupContractError("stop must be below entry")
        if target <= entry:
            raise SetupContractError("target must be above entry")
        if not isinstance(self.facts_hash, str) or not _HASH.fullmatch(self.facts_hash):
            raise SetupContractError("facts_hash must be lowercase SHA-256")
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "score_components", components)
        object.__setattr__(self, "entry", entry)
        object.__setattr__(self, "stop", stop)
        object.__setattr__(self, "target", target)


def _candidate_id(candidate: SetupCandidate) -> uuid.UUID:
    identity = ":".join(
        (
            str(candidate.run_id),
            candidate.ticker,
            candidate.strategy_id,
            candidate.strategy_version,
        )
    )
    return uuid.uuid5(_CANDIDATE_NAMESPACE, identity)


def persist_setup_candidate(conn, candidate: SetupCandidate) -> uuid.UUID:
    """Persist one immutable candidate after relationally checking every binding."""
    from psycopg.types.json import Jsonb

    if conn.execute("SELECT current_database()").fetchone()[0] != "wolfy_test":
        raise RuntimeError("setup candidate writes are disabled outside wolfy_test before release gate")
    binding = conn.execute(
        """SELECT run.universe_snapshot_id, gate.ticker, gate.strategy, gate.passed,
                  member.sector, member.included
             FROM daily_evaluation_runs AS run
             LEFT JOIN setup_gate_evaluations AS gate
               ON gate.id=%s AND gate.run_id=run.id
             LEFT JOIN recommendation_universe_members AS member
               ON member.snapshot_id=%s AND member.ticker=%s
            WHERE run.id=%s""",
        (
            candidate.gate_evaluation_id,
            candidate.universe_snapshot_id,
            candidate.ticker,
            candidate.run_id,
        ),
    ).fetchone()
    if binding is None:
        raise SetupContractError("candidate run does not exist")
    snapshot_id, gate_ticker, gate_strategy, gate_passed, member_sector, included = binding
    if snapshot_id != str(candidate.universe_snapshot_id):
        raise SetupContractError("candidate universe snapshot differs from immutable run")
    if (gate_ticker, gate_strategy) != (candidate.ticker, candidate.strategy_id):
        raise SetupContractError("candidate does not match its terminal gate")
    if gate_passed is not True:
        raise SetupContractError("candidate requires a passed terminal gate")
    if included is not True or member_sector != candidate.sector:
        raise SetupContractError("candidate must match an included universe member and sector")

    candidate_id = _candidate_id(candidate)
    payload = (
        candidate.run_id,
        candidate.universe_snapshot_id,
        candidate.gate_evaluation_id,
        candidate.ticker,
        candidate.strategy_id,
        candidate.strategy_version,
        candidate.sector,
        candidate.score,
        Jsonb({key: format(value, "f") for key, value in candidate.score_components.items()}),
        candidate.entry,
        candidate.stop,
        candidate.target,
        candidate.facts_hash,
    )
    inserted = conn.execute(
        """INSERT INTO setup_candidates(
               candidate_id,run_id,universe_snapshot_id,gate_evaluation_id,ticker,
               strategy_id,strategy_version,sector,score,score_components,
               entry,stop,target,facts_hash)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
             ON CONFLICT (candidate_id) DO NOTHING
             RETURNING candidate_id""",
        (candidate_id, *payload),
    ).fetchone()
    if inserted is not None:
        return inserted[0]
    stored = conn.execute(
        """SELECT run_id,universe_snapshot_id,gate_evaluation_id,ticker,strategy_id,
                  strategy_version,sector,score,score_components,entry,stop,target,facts_hash
             FROM setup_candidates WHERE candidate_id=%s""",
        (candidate_id,),
    ).fetchone()
    expected = (
        *payload[:8],
        {key: format(value, "f") for key, value in candidate.score_components.items()},
        *payload[9:],
    )
    if stored != expected:
        raise SetupContractError("setup candidate identity is immutable and conflicts with rerun")
    return candidate_id
