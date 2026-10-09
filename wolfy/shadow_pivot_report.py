"""Fail-closed evidence model for the mid/small-cap shadow release.

This module can inspect production only through an already read-only transaction.
It does not contain migration, recommendation, broker, delivery, or activation
credentials. Migration rehearsal is hard-bound to the dedicated ``wolfy_test``
database and executes caller-supplied reviewed SQL twice to prove rerunnability.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping, Sequence


REQUIRED_SHADOW_SCENARIOS = (
    "ordinary",
    "no_signal",
    "chain_unavailable",
    "sector_concentrated",
    "near_cap",
)
STRATEGY_SLEEVES = (
    "close_confirmed_breakout",
    "trend_pullback_reclaim",
    "volatility_contraction_breakout",
)
REQUIRED_RELEASE_GATES = (
    "benchmark_freshness",
    "universe_complete",
    "zero_ineligible_symbols",
    "breakout_parity",
    "deterministic_rerun",
    "malformed_inputs_rejected",
    "global_lock_concurrency",
    "position_cap",
    "sector_cap",
    "exact_risk_fraction",
    "aggregate_risk_cap",
    "instrument_provenance_or_fallback",
    "separate_outcomes",
    "zero_broker_write_capability",
    "migration_rehearsal",
    "full_suite",
)
_REQUIRED_REVIEWS = ("spec_compliance", "code_quality_security")
_BASELINE_TABLES = (
    "strategies",
    "recommendations",
    "paper_trades",
    "recommendation_outcomes",
    "option_outcomes",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MIGRATIONS_DIR = Path(__file__).resolve().with_name("migrations")
PIVOT_MIGRATIONS = tuple(
    _MIGRATIONS_DIR / name
    for name in (
        "20260917_daily_evaluation_ledger.sql",
        "20260917_option_snapshot_provenance.sql",
        "20260917_recommendation_uniqueness.sql",
        "20260917_security_master.sql",
        "20260917_recommendation_universe.sql",
        "20260917_setup_candidates.sql",
        "20260917_instrument_outcomes.sql",
    )
)
PIVOT_MIGRATION_SHA256 = (
    "ee52a2ce1b081c173db1d28404c97ea4681bfbb6300d32239081df143e4f1945",
    "90e1e7f86177c0f0c6b72666629b9c42da2a01cd4e3afb6c8ed49cd4e6ffbaeb",
    "671f6081fc318567ca5c8dc684c903f5870dd2393abd876a79cc8eb4b50ad5aa",
    "1e22e29f888d2ed38b79bc9aaae8f88715dea49d93bd2760730273c5e52a24be",
    "9a74c191c477700212bfd41c8b5be404c7bf1330eeb1ac83feb569ef2bb59bb3",
    "93464dc37423addd4711d41d8c082122149e44093d02f85a9608346333d50473",
    "dde5ab01ca844504a17fa2556f788f8ecc84413d9743b8f2e73485789a8802bd",
)


class ShadowReleaseEvidenceError(ValueError):
    """Malformed release evidence cannot be interpreted safely."""


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ShadowReleaseEvidenceError(f"{field} must be canonical lowercase SHA-256")
    return value


def _nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ShadowReleaseEvidenceError(f"{field} must be a nonnegative integer")
    return value


def _finite_decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ShadowReleaseEvidenceError(f"{field} must be a finite decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ShadowReleaseEvidenceError(f"{field} must be a finite decimal") from exc
    if not result.is_finite():
        raise ShadowReleaseEvidenceError(f"{field} must be a finite decimal")
    return result


@dataclass(frozen=True, slots=True)
class ProductionBaseline:
    database: str
    transaction_read_only: bool
    table_counts: Mapping[str, int]
    approved_metadata_sha256: str
    schema_versions: tuple[str, ...]
    present_tables: tuple[str, ...]
    table_content_sha256: Mapping[str, str]
    schema_sha256: str

    def __post_init__(self) -> None:
        if self.database != "wolfy":
            raise ShadowReleaseEvidenceError("baseline must identify production database wolfy")
        if self.transaction_read_only is not True:
            raise ShadowReleaseEvidenceError("production baseline must be read-only")
        if set(self.table_counts) != set(_BASELINE_TABLES):
            raise ShadowReleaseEvidenceError("production baseline table set is incomplete")
        normalized = {
            table: _nonnegative_int(self.table_counts[table], f"table_counts.{table}")
            for table in _BASELINE_TABLES
        }
        if not isinstance(self.schema_versions, tuple) or any(
            not isinstance(item, str) or not item for item in self.schema_versions
        ):
            raise ShadowReleaseEvidenceError("schema_versions must be a tuple of strings")
        if tuple(sorted(self.present_tables)) != self.present_tables or not set(
            self.present_tables
        ).issubset(_BASELINE_TABLES):
            raise ShadowReleaseEvidenceError("present_tables must be sorted and recognized")
        if set(self.table_content_sha256) != set(_BASELINE_TABLES):
            raise ShadowReleaseEvidenceError("table content fingerprint set is incomplete")
        fingerprints = {
            table: _sha256(
                self.table_content_sha256[table], f"table_content_sha256.{table}"
            )
            for table in _BASELINE_TABLES
        }
        object.__setattr__(self, "table_counts", normalized)
        object.__setattr__(self, "table_content_sha256", fingerprints)
        object.__setattr__(self, "schema_sha256", _sha256(self.schema_sha256, "schema_sha256"))
        object.__setattr__(
            self,
            "approved_metadata_sha256",
            _sha256(self.approved_metadata_sha256, "approved_metadata_sha256"),
        )


@dataclass(frozen=True, slots=True)
class ShadowReplayEvidence:
    scenario: str
    snapshot_fingerprint: str
    status: str
    input_fingerprint: str
    rerun_fingerprint: str
    benchmark_freshness: Decimal
    universe_complete: bool
    ineligible_symbols: int
    breakout_drift: int
    positions: int
    existing_positions: int
    candidates_attempted: int
    allocation_rejections: int
    maximum_sector_positions: int
    risk_fractions: tuple[str, ...]
    existing_risk_fractions: tuple[str, ...]
    aggregate_risk: str
    instrument_provenance_complete: bool
    expressions: tuple[str, ...]
    sleeves_evaluated: tuple[str, ...]
    outcomes_separate: bool
    recommendations_created: int
    paper_trades_created: int
    outcomes_created: int
    broker_orders_created: int
    external_deliveries: int

    def __post_init__(self) -> None:
        if self.scenario not in REQUIRED_SHADOW_SCENARIOS:
            raise ShadowReleaseEvidenceError(f"unknown shadow scenario:{self.scenario}")
        if not isinstance(self.status, str) or not self.status:
            raise ShadowReleaseEvidenceError("status must be non-empty")
        _sha256(self.snapshot_fingerprint, "replay.snapshot_fingerprint")
        _sha256(self.input_fingerprint, "input_fingerprint")
        _sha256(self.rerun_fingerprint, "rerun_fingerprint")
        freshness = _finite_decimal(self.benchmark_freshness, "benchmark_freshness")
        if freshness < 0 or freshness > 1:
            raise ShadowReleaseEvidenceError("benchmark_freshness must be between zero and one")
        for field in (
            "ineligible_symbols",
            "breakout_drift",
            "positions",
            "existing_positions",
            "candidates_attempted",
            "allocation_rejections",
            "maximum_sector_positions",
            "recommendations_created",
            "paper_trades_created",
            "outcomes_created",
            "broker_orders_created",
            "external_deliveries",
        ):
            _nonnegative_int(getattr(self, field), field)
        if not isinstance(self.risk_fractions, tuple) or not isinstance(
            self.existing_risk_fractions, tuple
        ):
            raise ShadowReleaseEvidenceError("risk fractions must be tuples")
        normalized_risks = tuple(
            str(_finite_decimal(value, "risk_fractions")) for value in self.risk_fractions
        )
        normalized_existing_risks = tuple(
            str(_finite_decimal(value, "existing_risk_fractions"))
            for value in self.existing_risk_fractions
        )
        aggregate = _finite_decimal(self.aggregate_risk, "aggregate_risk")
        if aggregate < 0:
            raise ShadowReleaseEvidenceError("aggregate_risk cannot be negative")
        for field in (
            "universe_complete",
            "instrument_provenance_complete",
            "outcomes_separate",
        ):
            if type(getattr(self, field)) is not bool:
                raise ShadowReleaseEvidenceError(f"{field} must be boolean")
        if not isinstance(self.expressions, tuple) or any(
            value
            not in {"long_call", "call_debit_spread", "underlying_stock_fallback"}
            for value in self.expressions
        ):
            raise ShadowReleaseEvidenceError("expressions contain an unsupported instrument")
        if self.sleeves_evaluated != STRATEGY_SLEEVES:
            raise ShadowReleaseEvidenceError("every replay must evaluate exactly three sleeves")
        object.__setattr__(self, "risk_fractions", normalized_risks)
        object.__setattr__(self, "existing_risk_fractions", normalized_existing_risks)
        object.__setattr__(self, "aggregate_risk", str(aggregate))
        object.__setattr__(self, "benchmark_freshness", freshness)


@dataclass(frozen=True, slots=True)
class IndependentReview:
    kind: str
    snapshot_fingerprint: str
    approved: bool
    findings: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.kind not in _REQUIRED_REVIEWS:
            raise ShadowReleaseEvidenceError(f"unknown review kind:{self.kind}")
        _sha256(self.snapshot_fingerprint, "review.snapshot_fingerprint")
        if type(self.approved) is not bool:
            raise ShadowReleaseEvidenceError("review approved must be boolean")
        if not isinstance(self.findings, tuple) or any(
            not isinstance(item, str) or not item for item in self.findings
        ):
            raise ShadowReleaseEvidenceError("review findings must be a tuple of strings")


@dataclass(frozen=True, slots=True)
class ReleaseGateEvidence:
    gate: str
    snapshot_fingerprint: str
    passed: bool
    artifact_sha256: str
    detail: str

    def __post_init__(self) -> None:
        if self.gate not in REQUIRED_RELEASE_GATES:
            raise ShadowReleaseEvidenceError(f"unknown release gate:{self.gate}")
        _sha256(self.snapshot_fingerprint, "gate.snapshot_fingerprint")
        _sha256(self.artifact_sha256, "gate.artifact_sha256")
        if type(self.passed) is not bool:
            raise ShadowReleaseEvidenceError("gate passed must be boolean")
        if not isinstance(self.detail, str) or not self.detail.strip():
            raise ShadowReleaseEvidenceError("gate detail must be non-empty")


@dataclass(frozen=True, slots=True)
class ShadowReleaseReport:
    snapshot_fingerprint: str
    approved: bool
    task23_preflight_eligible: bool
    production_activation_authorized: bool
    production_baselines_unchanged: bool
    failure_reasons: tuple[str, ...]
    replay_scenarios: tuple[str, ...]
    strategy_sleeves: tuple[str, ...] = STRATEGY_SLEEVES
    paper_only: bool = True
    no_live_execution: bool = True


@dataclass(frozen=True, slots=True)
class MigrationRehearsalResult:
    database: str
    passes: int
    migrations_applied: int
    migration_sha256: tuple[str, ...]


def _canonical_json_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def capture_production_baseline(conn) -> ProductionBaseline:
    """Capture counts and approval metadata through a read-only production transaction."""
    database, read_only = conn.execute(
        "SELECT current_database(), current_setting('transaction_read_only')"
    ).fetchone()
    if database != "wolfy":
        raise RuntimeError("production baseline requires production database wolfy")
    info = getattr(conn, "info", None)
    if (
        info is None
        or getattr(info, "host", None) != "/var/run/postgresql"
        or getattr(info, "user", None) != "root"
        or getattr(info, "dbname", None) != "wolfy"
    ):
        raise RuntimeError("production baseline requires expected local peer production")
    if read_only != "on":
        raise RuntimeError("production baseline requires an existing read-only transaction")

    existing = {
        row[0]
        for row in conn.execute(
            """SELECT table_name
                 FROM information_schema.tables
                WHERE table_schema='public'
                ORDER BY table_name"""
        ).fetchall()
    }
    counts: dict[str, int] = {}
    table_fingerprints: dict[str, str] = {}
    count_queries = {
        "strategies": "SELECT count(*) FROM strategies",
        "recommendations": "SELECT count(*) FROM recommendations",
        "paper_trades": "SELECT count(*) FROM paper_trades",
        "recommendation_outcomes": "SELECT count(*) FROM recommendation_outcomes",
        "option_outcomes": "SELECT count(*) FROM option_outcomes",
    }
    content_queries = {
        "strategies": "SELECT to_jsonb(t)::text FROM strategies AS t ORDER BY id",
        "recommendations": "SELECT to_jsonb(t)::text FROM recommendations AS t ORDER BY id",
        "paper_trades": "SELECT to_jsonb(t)::text FROM paper_trades AS t ORDER BY id",
        "recommendation_outcomes": "SELECT to_jsonb(t)::text FROM recommendation_outcomes AS t ORDER BY id",
        "option_outcomes": "SELECT to_jsonb(t)::text FROM option_outcomes AS t ORDER BY id",
    }
    for table in _BASELINE_TABLES:
        if table in existing:
            counts[table] = int(conn.execute(count_queries[table]).fetchone()[0])
            table_fingerprints[table] = _canonical_json_sha256(
                conn.execute(content_queries[table]).fetchall()
            )
        else:
            counts[table] = 0
            table_fingerprints[table] = "0" * 64

    approved_rows = conn.execute(
        """SELECT name,status,metadata
             FROM strategies
            WHERE status='approved'
            ORDER BY id,name"""
    ).fetchall()
    schema_versions: tuple[str, ...] = ()
    if "schema_migrations" in existing:
        columns = {
            row[0]
            for row in conn.execute(
                """SELECT column_name
                     FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='schema_migrations'"""
            ).fetchall()
        }
        version_column = next(
            (name for name in ("version", "name", "migration") if name in columns), None
        )
        if version_column is not None:
            version_queries = {
                "version": "SELECT version::text FROM schema_migrations ORDER BY version::text",
                "name": "SELECT name::text FROM schema_migrations ORDER BY name::text",
                "migration": "SELECT migration::text FROM schema_migrations ORDER BY migration::text",
            }
            schema_versions = tuple(
                row[0]
                for row in conn.execute(version_queries[version_column]).fetchall()
            )
    schema_evidence = (
        conn.execute(
            """SELECT table_name,column_name,data_type,is_nullable,column_default
                 FROM information_schema.columns
                WHERE table_schema='public'
                ORDER BY table_name,ordinal_position"""
        ).fetchall(),
        conn.execute(
            """SELECT tablename,indexname,indexdef
                 FROM pg_indexes
                WHERE schemaname='public'
                ORDER BY tablename,indexname"""
        ).fetchall(),
        conn.execute(
            """SELECT c.conrelid::regclass::text,c.conname,pg_get_constraintdef(c.oid)
                 FROM pg_constraint c
                 JOIN pg_namespace n ON n.oid=c.connamespace
                WHERE n.nspname='public'
                ORDER BY 1,2"""
        ).fetchall(),
        conn.execute(
            """SELECT event_object_table,trigger_name,action_statement
                 FROM information_schema.triggers
                WHERE trigger_schema='public'
                ORDER BY event_object_table,trigger_name"""
        ).fetchall(),
    )
    return ProductionBaseline(
        database=database,
        transaction_read_only=True,
        table_counts=counts,
        approved_metadata_sha256=_canonical_json_sha256(approved_rows),
        schema_versions=schema_versions,
        present_tables=tuple(sorted(set(_BASELINE_TABLES).intersection(existing))),
        table_content_sha256=table_fingerprints,
        schema_sha256=_canonical_json_sha256(schema_evidence),
    )


def rehearse_pivot_migrations(conn) -> MigrationRehearsalResult:
    """Apply the fixed reviewed migration set twice on local peer wolfy_test."""
    database = conn.execute("SELECT current_database()").fetchone()[0]
    info = getattr(conn, "info", None)
    if database != "wolfy_test":
        raise RuntimeError("migration rehearsal is restricted to wolfy_test")
    if (
        info is None
        or getattr(info, "host", None) != "/var/run/postgresql"
        or getattr(info, "user", None) != "root"
        or getattr(info, "dbname", None) != "wolfy_test"
    ):
        raise RuntimeError("migration rehearsal requires local peer wolfy_test")
    if getattr(conn, "autocommit", None) is not True:
        raise RuntimeError("migration rehearsal requires autocommit pass boundaries")
    migration_bytes = tuple(path.read_bytes() for path in PIVOT_MIGRATIONS)
    payload_hashes = tuple(hashlib.sha256(payload).hexdigest() for payload in migration_bytes)
    if payload_hashes != PIVOT_MIGRATION_SHA256:
        raise RuntimeError("reviewed migration hash mismatch")
    try:
        sql_payloads = tuple(payload.decode("utf-8") for payload in migration_bytes)
    except UnicodeDecodeError as exc:
        raise RuntimeError("reviewed migration is not UTF-8") from exc
    if any(not sql.strip() for sql in sql_payloads):
        raise ShadowReleaseEvidenceError("reviewed migration SQL must not be empty")
    for _ in range(2):
        for migration_sql in sql_payloads:
            conn.execute(migration_sql)
    return MigrationRehearsalResult(
        database=database,
        passes=2,
        migrations_applied=len(sql_payloads) * 2,
        migration_sha256=payload_hashes,
    )


def _replay_failures(replay: ShadowReplayEvidence) -> list[str]:
    failures: list[str] = []
    expected_status = {
        "ordinary": "shadow_complete",
        "no_signal": "no_candidates",
        "chain_unavailable": "shadow_complete",
        "sector_concentrated": "shadow_complete",
        "near_cap": "shadow_complete",
    }[replay.scenario]
    if replay.status != expected_status:
        failures.append(f"scenario_status_invalid:{replay.scenario}")
    if replay.scenario == "no_signal" and any(
        (
            replay.candidates_attempted,
            replay.positions,
            replay.allocation_rejections,
            len(replay.expressions),
        )
    ):
        failures.append("no_signal_scenario_not_empty")
    if replay.scenario == "chain_unavailable" and replay.positions < 1:
        failures.append("chain_unavailable_not_exercised")
    if replay.input_fingerprint != replay.rerun_fingerprint:
        failures.append(f"non_deterministic_replay:{replay.scenario}")
    if any(
        value != 0
        for value in (
            replay.recommendations_created,
            replay.paper_trades_created,
            replay.outcomes_created,
            replay.broker_orders_created,
            replay.external_deliveries,
        )
    ):
        failures.append(f"shadow_side_effect:{replay.scenario}")
    if replay.benchmark_freshness != 1.0:
        failures.append(f"benchmark_freshness_incomplete:{replay.scenario}")
    if not replay.universe_complete:
        failures.append(f"universe_incomplete:{replay.scenario}")
    if replay.ineligible_symbols:
        failures.append(f"ineligible_symbol_present:{replay.scenario}")
    if replay.breakout_drift:
        failures.append(f"breakout_drift:{replay.scenario}")
    total_positions = replay.existing_positions + replay.positions
    if replay.candidates_attempted != replay.positions + replay.allocation_rejections:
        failures.append(f"allocation_accounting_invalid:{replay.scenario}")
    if replay.scenario != "no_signal" and replay.candidates_attempted < 1:
        failures.append(f"scenario_not_exercised:{replay.scenario}")
    if replay.scenario == "sector_concentrated" and not (
        replay.candidates_attempted > 5
        and replay.positions == 5
        and replay.allocation_rejections >= 1
        and replay.maximum_sector_positions == 5
    ):
        failures.append("sector_concentration_boundary_not_exercised")
    if replay.scenario == "near_cap" and not (
        replay.existing_positions == 19
        and replay.candidates_attempted >= 2
        and replay.positions == 1
        and replay.allocation_rejections >= 1
        and total_positions == 20
    ):
        failures.append("near_cap_boundary_not_exercised")
    if total_positions > 20:
        failures.append(f"position_cap_exceeded:{replay.scenario}")
    if replay.maximum_sector_positions > 5 or replay.maximum_sector_positions > total_positions:
        failures.append(f"sector_cap_exceeded:{replay.scenario}")
    if len(replay.risk_fractions) != replay.positions or any(
        Decimal(value) != Decimal("0.05") for value in replay.risk_fractions
    ):
        failures.append(f"risk_fraction_drift:{replay.scenario}")
    if len(replay.existing_risk_fractions) != replay.existing_positions or any(
        Decimal(value) != Decimal("0.05") for value in replay.existing_risk_fractions
    ):
        failures.append(f"existing_risk_fraction_drift:{replay.scenario}")
    expected_risk = sum(
        (Decimal(value) for value in replay.risk_fractions + replay.existing_risk_fractions),
        Decimal("0"),
    )
    if Decimal(replay.aggregate_risk) != expected_risk or expected_risk > Decimal("1"):
        failures.append(f"aggregate_risk_exceeded:{replay.scenario}")
    if len(replay.expressions) != replay.positions:
        failures.append(f"instrument_count_mismatch:{replay.scenario}")
    if replay.scenario == "chain_unavailable" and any(
        value != "underlying_stock_fallback" for value in replay.expressions
    ):
        failures.append("chain_unavailable_without_fallback")
    if not replay.instrument_provenance_complete:
        failures.append(f"instrument_provenance_incomplete:{replay.scenario}")
    if not replay.outcomes_separate:
        failures.append(f"outcome_separation_failed:{replay.scenario}")
    return failures


def build_shadow_release_report(
    *,
    snapshot_fingerprint: str,
    production_before: ProductionBaseline,
    production_after: ProductionBaseline,
    replays: Sequence[ShadowReplayEvidence],
    gate_results: Mapping[str, ReleaseGateEvidence],
    migration_rehearsal: MigrationRehearsalResult,
    reviews: Sequence[IndependentReview],
) -> ShadowReleaseReport:
    """Evaluate Task 22 evidence; never authorize production activation itself."""
    snapshot = _sha256(snapshot_fingerprint, "snapshot_fingerprint")
    if not isinstance(production_before, ProductionBaseline) or not isinstance(
        production_after, ProductionBaseline
    ):
        raise TypeError("production baselines must be ProductionBaseline values")
    failures: list[str] = []
    production_unchanged = production_before == production_after
    if not production_unchanged:
        failures.append("production_baseline_changed")

    if set(gate_results) != set(REQUIRED_RELEASE_GATES):
        failures.append("release_gate_set_incomplete")
    for gate in REQUIRED_RELEASE_GATES:
        evidence = gate_results.get(gate)
        if not isinstance(evidence, ReleaseGateEvidence) or evidence.gate != gate:
            failures.append(f"release_gate_evidence_invalid:{gate}")
            continue
        if evidence.snapshot_fingerprint != snapshot:
            failures.append(f"release_gate_snapshot_mismatch:{gate}")
        if evidence.passed is not True:
            failures.append(f"release_gate_failed:{gate}")

    expected_migration_hashes = PIVOT_MIGRATION_SHA256
    if (
        not isinstance(migration_rehearsal, MigrationRehearsalResult)
        or migration_rehearsal.database != "wolfy_test"
        or migration_rehearsal.passes != 2
        or migration_rehearsal.migrations_applied != len(PIVOT_MIGRATIONS) * 2
        or migration_rehearsal.migration_sha256 != expected_migration_hashes
    ):
        failures.append("migration_rehearsal_invalid")

    scenario_rows: dict[str, ShadowReplayEvidence] = {}
    for replay in replays:
        if not isinstance(replay, ShadowReplayEvidence):
            raise ShadowReleaseEvidenceError("replays contain malformed evidence")
        if replay.scenario in scenario_rows:
            failures.append(f"duplicate_shadow_scenario:{replay.scenario}")
        if replay.snapshot_fingerprint != snapshot:
            failures.append(f"replay_snapshot_mismatch:{replay.scenario}")
        scenario_rows[replay.scenario] = replay
        failures.extend(_replay_failures(replay))
    for scenario in REQUIRED_SHADOW_SCENARIOS:
        if scenario not in scenario_rows:
            failures.append(f"missing_shadow_scenario:{scenario}")

    review_rows: dict[str, IndependentReview] = {}
    for review in reviews:
        if not isinstance(review, IndependentReview):
            raise ShadowReleaseEvidenceError("reviews contain malformed evidence")
        if review.kind in review_rows:
            failures.append(f"duplicate_review:{review.kind}")
        review_rows[review.kind] = review
    for kind in _REQUIRED_REVIEWS:
        review = review_rows.get(kind)
        if review is None:
            failures.append(f"missing_review:{kind}")
            continue
        if review.snapshot_fingerprint != snapshot:
            failures.append(f"review_snapshot_mismatch:{kind}")
        if not review.approved or review.findings:
            failures.append(f"review_not_approved:{kind}")

    unique_failures = tuple(dict.fromkeys(failures))
    approved = not unique_failures
    return ShadowReleaseReport(
        snapshot_fingerprint=snapshot,
        approved=approved,
        task23_preflight_eligible=approved,
        production_activation_authorized=False,
        production_baselines_unchanged=production_unchanged,
        failure_reasons=unique_failures,
        replay_scenarios=tuple(
            scenario for scenario in REQUIRED_SHADOW_SCENARIOS if scenario in scenario_rows
        ),
    )
