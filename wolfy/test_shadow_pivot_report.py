from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest


SNAPSHOT = "b" * 64
REQUIRED_SCENARIOS = (
    "ordinary",
    "no_signal",
    "chain_unavailable",
    "sector_concentrated",
    "near_cap",
)
REQUIRED_GATES = (
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


def _baseline():
    from shadow_pivot_report import ProductionBaseline

    return ProductionBaseline(
        database="wolfy",
        transaction_read_only=True,
        table_counts={
            "strategies": 7,
            "recommendations": 569,
            "paper_trades": 2,
            "recommendation_outcomes": 2,
            "option_outcomes": 0,
        },
        approved_metadata_sha256="a" * 64,
        schema_versions=(),
        present_tables=(
            "paper_trades",
            "recommendation_outcomes",
            "recommendations",
            "strategies",
        ),
        table_content_sha256={
            "strategies": "1" * 64,
            "recommendations": "2" * 64,
            "paper_trades": "3" * 64,
            "recommendation_outcomes": "4" * 64,
            "option_outcomes": "0" * 64,
        },
        schema_sha256="5" * 64,
    )


def _replay(scenario: str, **overrides):
    from shadow_pivot_report import ShadowReplayEvidence

    values = {
        "scenario": scenario,
        "snapshot_fingerprint": SNAPSHOT,
        "status": "shadow_complete",
        "input_fingerprint": hashlib.sha256(scenario.encode()).hexdigest(),
        "rerun_fingerprint": hashlib.sha256(scenario.encode()).hexdigest(),
        "benchmark_freshness": 1.0,
        "universe_complete": True,
        "ineligible_symbols": 0,
        "breakout_drift": 0,
        "positions": 1,
        "existing_positions": 0,
        "candidates_attempted": 1,
        "allocation_rejections": 0,
        "maximum_sector_positions": 1,
        "risk_fractions": ("0.05",),
        "existing_risk_fractions": (),
        "aggregate_risk": "0.05",
        "instrument_provenance_complete": True,
        "expressions": ("underlying_stock_fallback",),
        "sleeves_evaluated": (
            "close_confirmed_breakout",
            "trend_pullback_reclaim",
            "volatility_contraction_breakout",
        ),
        "outcomes_separate": True,
        "recommendations_created": 0,
        "paper_trades_created": 0,
        "outcomes_created": 0,
        "broker_orders_created": 0,
        "external_deliveries": 0,
    }
    if scenario == "no_signal":
        values.update(
            status="no_candidates",
            positions=0,
            candidates_attempted=0,
            maximum_sector_positions=0,
            risk_fractions=(),
            aggregate_risk="0",
            expressions=(),
        )
    elif scenario == "sector_concentrated":
        values.update(
            positions=5,
            candidates_attempted=7,
            allocation_rejections=2,
            maximum_sector_positions=5,
            risk_fractions=("0.05",) * 5,
            aggregate_risk="0.25",
            expressions=("underlying_stock_fallback",) * 5,
        )
    elif scenario == "near_cap":
        values.update(
            existing_positions=19,
            candidates_attempted=2,
            allocation_rejections=1,
            existing_risk_fractions=("0.05",) * 19,
            aggregate_risk="1.00",
        )
    values.update(overrides)
    return ShadowReplayEvidence(**values)


def _reviews(snapshot: str):
    from shadow_pivot_report import IndependentReview

    return (
        IndependentReview("spec_compliance", snapshot, True, ()),
        IndependentReview("code_quality_security", snapshot, True, ()),
    )


def _gates(snapshot: str):
    from shadow_pivot_report import ReleaseGateEvidence

    return {
        name: ReleaseGateEvidence(
            name,
            snapshot,
            True,
            hashlib.sha256(name.encode()).hexdigest(),
            "verified",
        )
        for name in REQUIRED_GATES
    }


def _migration_rehearsal():
    from shadow_pivot_report import (
        MigrationRehearsalResult,
        PIVOT_MIGRATIONS,
        PIVOT_MIGRATION_SHA256,
    )

    assert tuple(
        hashlib.sha256(path.read_bytes()).hexdigest() for path in PIVOT_MIGRATIONS
    ) == PIVOT_MIGRATION_SHA256
    return MigrationRehearsalResult(
        database="wolfy_test",
        passes=2,
        migrations_applied=len(PIVOT_MIGRATIONS) * 2,
        migration_sha256=PIVOT_MIGRATION_SHA256,
    )


def _report(**overrides):
    from shadow_pivot_report import build_shadow_release_report

    snapshot = SNAPSHOT
    values = {
        "snapshot_fingerprint": snapshot,
        "production_before": _baseline(),
        "production_after": _baseline(),
        "replays": tuple(_replay(name) for name in REQUIRED_SCENARIOS),
        "gate_results": _gates(snapshot),
        "migration_rehearsal": _migration_rehearsal(),
        "reviews": _reviews(snapshot),
    }
    values.update(overrides)
    return build_shadow_release_report(**values)


def test_release_report_requires_five_scenarios_gates_migrations_and_reviews():
    report = _report()

    assert report.approved is True
    assert report.task23_preflight_eligible is True
    assert report.production_activation_authorized is False
    assert report.paper_only is True
    assert report.no_live_execution is True
    assert report.production_baselines_unchanged is True
    assert report.strategy_sleeves == (
        "close_confirmed_breakout",
        "trend_pullback_reclaim",
        "volatility_contraction_breakout",
    )
    assert report.failure_reasons == ()


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("missing_scenario", "missing_shadow_scenario:near_cap"),
        ("production_delta", "production_baseline_changed"),
        ("failed_gate", "release_gate_failed:full_suite"),
        ("wrong_snapshot", "review_snapshot_mismatch:spec_compliance"),
        ("replay_wrong_snapshot", "replay_snapshot_mismatch:ordinary"),
        ("broker_action", "shadow_side_effect:ordinary"),
        ("non_deterministic", "non_deterministic_replay:ordinary"),
        ("risk_drift", "risk_fraction_drift:ordinary"),
        ("bad_status", "scenario_status_invalid:ordinary"),
        ("missing_fallback", "chain_unavailable_without_fallback"),
    ],
)
def test_release_report_fails_closed(mutation: str, reason: str):
    snapshot = SNAPSHOT
    baseline_after = _baseline()
    replays = [_replay(name) for name in REQUIRED_SCENARIOS]
    gates = _gates(snapshot)
    reviews = list(_reviews(snapshot))
    if mutation == "missing_scenario":
        replays.pop()
    elif mutation == "production_delta":
        baseline_after = replace(
            baseline_after,
            table_counts={**baseline_after.table_counts, "recommendations": 570},
        )
    elif mutation == "failed_gate":
        gates["full_suite"] = replace(gates["full_suite"], passed=False)
    elif mutation == "wrong_snapshot":
        reviews[0] = replace(reviews[0], snapshot_fingerprint="c" * 64)
    elif mutation == "replay_wrong_snapshot":
        replays[0] = replace(replays[0], snapshot_fingerprint="c" * 64)
    elif mutation == "broker_action":
        replays[0] = replace(replays[0], broker_orders_created=1)
    elif mutation == "non_deterministic":
        replays[0] = replace(replays[0], rerun_fingerprint="d" * 64)
    elif mutation == "risk_drift":
        replays[0] = replace(replays[0], risk_fractions=("0.04",))
    elif mutation == "bad_status":
        replays[0] = replace(replays[0], status="skipped")
    elif mutation == "missing_fallback":
        replays[2] = replace(replays[2], expressions=("long_call",))

    report = _report(
        production_after=baseline_after,
        replays=tuple(replays),
        gate_results=gates,
        reviews=tuple(reviews),
    )
    assert report.approved is False
    assert report.task23_preflight_eligible is False
    assert report.production_activation_authorized is False
    assert reason in report.failure_reasons


def test_release_report_rejects_fabricated_baseline_and_wrong_migration_evidence():
    with pytest.raises(TypeError, match="ProductionBaseline"):
        _report(production_before=object())
    bad = replace(_migration_rehearsal(), passes=1)
    report = _report(migration_rehearsal=bad)
    assert "migration_rehearsal_invalid" in report.failure_reasons


def test_capture_production_baseline_requires_read_only_and_hashes_table_contents():
    from shadow_pivot_report import capture_production_baseline

    class Cursor:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return self.value

        def fetchall(self):
            return self.value

    class FakeConnection:
        def __init__(self, *, database="wolfy", read_only="on"):
            self.database = database
            self.read_only = read_only
            self.info = type(
                "Info",
                (),
                {
                    "host": "/var/run/postgresql",
                    "user": "root",
                    "dbname": database,
                },
            )()

        def execute(self, statement, params=None):
            del params
            normalized = " ".join(statement.split()).lower()
            if "current_database()" in normalized:
                return Cursor((self.database, self.read_only))
            if "from information_schema.tables" in normalized:
                return Cursor(
                    [(name,) for name in (
                        "paper_trades",
                        "recommendation_outcomes",
                        "recommendations",
                        "strategies",
                    )]
                )
            if normalized.startswith("select count(*) from"):
                table = normalized.rsplit(" ", 1)[-1]
                counts = {"strategies": 7, "recommendations": 569, "paper_trades": 2, "recommendation_outcomes": 2}
                return Cursor((counts[table],))
            if normalized.startswith("select to_jsonb"):
                table = normalized.split(" from ", 1)[1].split()[0]
                return Cursor([(f"{table}-row",)])
            if "from strategies" in normalized:
                return Cursor([("approved", "approved", {"paper_only": True})])
            if (
                "from information_schema.columns" in normalized
                or "from pg_indexes" in normalized
                or "from pg_constraint" in normalized
                or "from information_schema.triggers" in normalized
            ):
                return Cursor([])
            raise AssertionError(statement)

    first = capture_production_baseline(FakeConnection())
    second = capture_production_baseline(FakeConnection())
    assert first == second
    assert first.table_counts["option_outcomes"] == 0
    assert first.table_content_sha256["option_outcomes"] == "0" * 64
    assert len(first.table_content_sha256["recommendations"]) == 64

    with pytest.raises(RuntimeError, match="read-only"):
        capture_production_baseline(FakeConnection(read_only="off"))
    with pytest.raises(RuntimeError, match="production database"):
        capture_production_baseline(FakeConnection(database="wolfy_test"))


def test_rehearse_pivot_migrations_runs_reviewed_set_twice_only_on_local_wolfy_test():
    from shadow_pivot_report import PIVOT_MIGRATIONS, rehearse_pivot_migrations

    class Cursor:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return self.value

    class FakeConnection:
        def __init__(self, database="wolfy_test", *, autocommit=True):
            self.database = database
            self.statements = []
            self.autocommit = autocommit
            self.info = type(
                "Info",
                (),
                {"host": "/var/run/postgresql", "user": "root", "dbname": database},
            )()

        def execute(self, statement):
            if statement == "SELECT current_database()":
                return Cursor((self.database,))
            self.statements.append(statement)
            return Cursor(None)

    conn = FakeConnection()
    result = rehearse_pivot_migrations(conn)
    expected = [path.read_text(encoding="utf-8") for path in PIVOT_MIGRATIONS]
    assert conn.statements == expected + expected
    assert result.database == "wolfy_test"
    assert result.passes == 2
    assert result.migrations_applied == len(PIVOT_MIGRATIONS) * 2

    with pytest.raises(RuntimeError, match="wolfy_test"):
        rehearse_pivot_migrations(FakeConnection("wolfy"))
    with pytest.raises(RuntimeError, match="autocommit"):
        rehearse_pivot_migrations(FakeConnection(autocommit=False))
    remote = FakeConnection()
    remote.info.host = "db.example"
    with pytest.raises(RuntimeError, match="local peer"):
        rehearse_pivot_migrations(remote)


def test_rehearse_reviewed_migrations_twice_on_real_wolfy_test():
    import psycopg

    from shadow_pivot_report import PIVOT_MIGRATION_SHA256, rehearse_pivot_migrations
    from test_db import resolve_test_dsn

    with psycopg.connect(resolve_test_dsn(), autocommit=True) as conn:
        result = rehearse_pivot_migrations(conn)
    assert result.database == "wolfy_test"
    assert result.passes == 2
    assert result.migration_sha256 == PIVOT_MIGRATION_SHA256
