from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from test_db import test_connection

UTC = timezone.utc


def _now() -> datetime:
    return datetime(2099, 3, 2, 20, tzinfo=UTC)


def _create_run(conn, **overrides):
    from daily_evaluation_ledger import DailyRunIdentity, create_daily_run

    values = {
        "target_session": date(2099, 3, 2),
        "evaluator_name": "daily-multi-setup",
        "evaluator_version": "1.0.0",
        "universe_snapshot_id": "universe-20990302-v1",
    }
    values.update(overrides)
    return create_daily_run(conn, DailyRunIdentity(**values))


def test_create_daily_run_has_deterministic_unique_identity_and_idempotent_rerun():
    with test_connection() as conn:
        first = _create_run(conn)
        second = _create_run(conn)

        count = conn.execute(
            "SELECT count(*) FROM daily_evaluation_runs WHERE id=%s", (first.run_id,)
        ).fetchone()[0]
        assert first == second
        assert first.status == "started"
        assert count == 1


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (("data_incomplete", "evaluated"), "evaluated"),
        (("evaluated",), "evaluated"),
        (("failed",), "failed"),
        (("data_incomplete", "failed"), "failed"),
        (("evaluated", "failed"), "failed"),
    ],
)
def test_daily_run_allows_only_forward_status_transitions(path, expected):
    from daily_evaluation_ledger import transition_daily_run

    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id=f"legal-{'-'.join(path)}")
        for status in path:
            run = transition_daily_run(conn, run.run_id, status)
        assert run.status == expected


@pytest.mark.parametrize(
    ("path", "invalid"),
    [
        (("evaluated",), "started"),
        (("data_incomplete",), "started"),
        (("failed",), "started"),
        ((), "published"),
    ],
)
def test_daily_run_rejects_invalid_or_reverse_transitions(path, invalid):
    from daily_evaluation_ledger import InvalidRunTransition, transition_daily_run

    with test_connection() as conn:
        run = _create_run(
            conn, universe_snapshot_id=f"invalid-{invalid}-{'-'.join(path)}"
        )
        for status in path:
            run = transition_daily_run(conn, run.run_id, status)
        with pytest.raises(InvalidRunTransition):
            transition_daily_run(conn, run.run_id, invalid)


def test_database_constraint_rejects_invalid_status_and_transition():
    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id="direct-sql-guard")
        with pytest.raises(Exception), conn.transaction():
            conn.execute(
                "UPDATE daily_evaluation_runs SET status='bogus' WHERE id=%s",
                (run.run_id,),
            )
        with pytest.raises(Exception), conn.transaction():
            conn.execute(
                "UPDATE daily_evaluation_runs SET status='published' WHERE id=%s",
                (run.run_id,),
            )


def _manifest(**overrides):
    from daily_evaluation_ledger import IngestionManifest

    values = {
        "dataset": "eod_aggregates",
        "target_session": date(2099, 3, 2),
        "provider": "massive",
        "source_endpoint": "/v2/aggs/ticker/{symbol}/range/1/day",
        "entitlement_class": "free",
        "delay_class": "t_plus_1",
        "started_at": _now(),
        "completed_at": _now() + timedelta(minutes=2),
        "expected_symbol_count": 100,
        "received_symbol_count": 100,
        "expected_row_count": 100,
        "received_row_count": 100,
        "retry_count": 1,
        "status": "completed",
        "raw_payload_sha256": "a" * 64,
        "immutable_object_ref": None,
        "parser_version": "aggs-parser-2",
        "schema_version": "eod-bars-3",
        "quality_gate": "passed",
        "provenance": {"request_id": "req-123", "shard": 0},
    }
    values.update(overrides)
    return IngestionManifest(**values)


def test_ingestion_manifest_persists_counts_hash_and_is_deterministic_upsert():
    from daily_evaluation_ledger import upsert_ingestion_manifest

    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id="manifest-upsert")
        first = upsert_ingestion_manifest(conn, run.run_id, _manifest())
        revised = _manifest(received_row_count=99, quality_gate="failed")
        second = upsert_ingestion_manifest(conn, run.run_id, revised)
        row = conn.execute(
            """
            SELECT expected_symbol_count, received_symbol_count,
                   expected_row_count, received_row_count, raw_payload_sha256,
                   parser_version, schema_version, quality_gate, provenance
            FROM ingestion_run_manifests WHERE id=%s
            """,
            (first,),
        ).fetchone()
        assert first == second
        assert row == (
            100,
            100,
            100,
            99,
            "a" * 64,
            "aggs-parser-2",
            "eod-bars-3",
            "failed",
            {"shard": 0, "request_id": "req-123"},
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"raw_payload_sha256": "not-a-hash"},
        {"raw_payload_sha256": None, "immutable_object_ref": None},
        {"raw_payload_sha256": "a" * 64, "immutable_object_ref": "s3://immutable/key"},
        {"started_at": datetime(2099, 3, 2, 20)},
        {"completed_at": datetime(2099, 3, 2, 20)},
        {"received_row_count": -1},
        {"status": "complete"},
        {"quality_gate": "ok"},
        {"provenance": ["not", "an", "object"]},
    ],
)
def test_ingestion_manifest_fails_closed_on_invalid_values(overrides):
    from daily_evaluation_ledger import LedgerValidationError, upsert_ingestion_manifest

    with test_connection() as conn:
        run = _create_run(
            conn, universe_snapshot_id=f"bad-manifest-{len(str(overrides))}"
        )
        with pytest.raises(LedgerValidationError):
            upsert_ingestion_manifest(conn, run.run_id, _manifest(**overrides))


def _gate(**overrides):
    from daily_evaluation_ledger import GateEvaluation

    values = {
        "ticker": "ZZLEDGER",
        "strategy": "liquid_rs_breakout",
        "passed": False,
        "reason_code_version": 1,
        "reason_codes": ("breakout_failed", "volume_confirmation_failed"),
        "evaluated_at": _now(),
        "metrics": {"close": "101.25", "breakout_level": "102.00"},
        "provenance": {"feature_row_id": 42},
    }
    values.update(overrides)
    return GateEvaluation(**values)


def test_gate_evaluation_is_one_row_per_run_ticker_strategy_with_upsert():
    from daily_evaluation_ledger import upsert_gate_evaluation

    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id="gate-upsert")
        first = upsert_gate_evaluation(conn, run.run_id, _gate())
        second = upsert_gate_evaluation(
            conn,
            run.run_id,
            _gate(reason_codes=("relative_strength_failed",), metrics={"rs": "0.01"}),
        )
        row = conn.execute(
            """
            SELECT passed, reason_code_version, reason_codes, metrics, provenance
            FROM setup_gate_evaluations WHERE id=%s
            """,
            (first,),
        ).fetchone()
        assert first == second
        assert row == (
            False,
            1,
            ["relative_strength_failed"],
            {"rs": "0.01"},
            {"feature_row_id": 42},
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"reason_code_version": 2},
        {"reason_codes": ("unknown_reason",)},
        {"reason_codes": ("volume_confirmation_failed", "breakout_failed")},
        {"reason_codes": ("breakout_failed", "breakout_failed")},
        {"ticker": "zzledger"},
        {"evaluated_at": datetime(2099, 3, 2, 20)},
        {"metrics": []},
        {"provenance": []},
    ],
)
def test_gate_evaluation_rejects_noncanonical_reasons_and_provenance(overrides):
    from daily_evaluation_ledger import LedgerValidationError, upsert_gate_evaluation

    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id=f"bad-gate-{len(str(overrides))}")
        with pytest.raises(LedgerValidationError):
            upsert_gate_evaluation(conn, run.run_id, _gate(**overrides))


def _derived(**overrides):
    from daily_evaluation_ledger import DerivedStageMetadata

    values = {
        "stage_name": "features",
        "input_session": date(2099, 3, 2),
        "computed_at": _now() + timedelta(minutes=3),
        "available_at": _now() + timedelta(minutes=4),
        "transformation_version": "feature-pipeline-5",
        "source_run_ids": ("massive-ingest-20990302",),
        "input_hash": "b" * 64,
        "universe_snapshot_id": "publish-ready",
        "provenance": {"code_commit": "abc123"},
    }
    values.update(overrides)
    return DerivedStageMetadata(**values)


def test_derived_stage_metadata_persists_required_audit_fields_idempotently():
    from daily_evaluation_ledger import record_derived_stage_metadata

    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id="publish-ready")
        record_derived_stage_metadata(conn, run.run_id, _derived())
        record_derived_stage_metadata(
            conn,
            run.run_id,
            _derived(transformation_version="feature-pipeline-6"),
        )
        metadata = conn.execute(
            "SELECT derived_stage_metadata->'features' FROM daily_evaluation_runs WHERE id=%s",
            (run.run_id,),
        ).fetchone()[0]
        assert metadata["input_session"] == "2099-03-02"
        assert metadata["computed_at"] == "2099-03-02T20:03:00+00:00"
        assert metadata["available_at"] == "2099-03-02T20:04:00+00:00"
        assert metadata["transformation_version"] == "feature-pipeline-6"
        assert metadata["source_run_ids"] == ["massive-ingest-20990302"]
        assert metadata["input_hash"] == "b" * 64
        assert metadata["universe_snapshot_id"] == "publish-ready"
        assert metadata["provenance"] == {"code_commit": "abc123"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"stage_name": ""},
        {"stage_name": " features "},
        {"computed_at": None},
        {"computed_at": "2099-03-02T20:03:00+00:00"},
        {"computed_at": datetime(2099, 3, 2, 20)},
        {"available_at": datetime(2099, 3, 2, 20)},
        {"available_at": _now() + timedelta(minutes=2)},
        {"transformation_version": ""},
        {"transformation_version": " feature-pipeline-5 "},
        {"source_run_ids": ()},
        {"source_run_ids": (" source-run ",)},
        {"source_run_ids": ("source-run", 3)},
        {"source_run_ids": ("source-run", "source-run")},
        {"input_hash": "bad"},
        {"input_hash": "B" * 64},
        {"universe_snapshot_id": ""},
        {"universe_snapshot_id": " publish-ready "},
        {"provenance": []},
    ],
)
def test_derived_stage_metadata_rejects_incomplete_or_noncanonical_values(overrides):
    from daily_evaluation_ledger import (
        LedgerValidationError,
        record_derived_stage_metadata,
    )

    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id="publish-ready")
        with pytest.raises(LedgerValidationError):
            record_derived_stage_metadata(conn, run.run_id, _derived(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"stage_name": "ranking"},
        {"universe_snapshot_id": "other-snapshot"},
        {"input_session": date(2099, 3, 1)},
    ],
)
def test_derived_stage_metadata_must_match_immutable_run_contract(overrides):
    from daily_evaluation_ledger import (
        LedgerValidationError,
        record_derived_stage_metadata,
    )

    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id="publish-ready")
        with pytest.raises(LedgerValidationError):
            record_derived_stage_metadata(conn, run.run_id, _derived(**overrides))


def test_published_requires_passed_manifest_and_every_required_derived_stage():
    from daily_evaluation_ledger import (
        LedgerValidationError,
        record_derived_stage_metadata,
        transition_daily_run,
        upsert_ingestion_manifest,
    )

    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id="publish-ready")
        transition_daily_run(conn, run.run_id, "evaluated")
        with pytest.raises(LedgerValidationError, match="manifest"):
            transition_daily_run(conn, run.run_id, "published")

        upsert_ingestion_manifest(conn, run.run_id, _manifest())
        with pytest.raises(LedgerValidationError, match="derived stage"):
            transition_daily_run(conn, run.run_id, "published")

        record_derived_stage_metadata(conn, run.run_id, _derived())
        published = transition_daily_run(conn, run.run_id, "published")
        assert published.status == "published"
        assert transition_daily_run(conn, run.run_id, "published") == published


def test_database_rejects_published_when_required_metadata_is_incomplete():
    from daily_evaluation_ledger import transition_daily_run

    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id="db-publish-guard")
        transition_daily_run(conn, run.run_id, "evaluated")
        with pytest.raises(Exception), conn.transaction():
            conn.execute(
                "UPDATE daily_evaluation_runs SET status='published' WHERE id=%s",
                (run.run_id,),
            )


@pytest.mark.parametrize(
    "manifest_overrides",
    [
        {"target_session": date(2099, 3, 1)},
        {"received_symbol_count": 99},
        {"received_row_count": 99},
        {"quality_gate": "failed"},
    ],
)
def test_published_rejects_manifest_that_is_not_complete_for_target_session(
    manifest_overrides,
):
    from daily_evaluation_ledger import (
        LedgerValidationError,
        record_derived_stage_metadata,
        transition_daily_run,
        upsert_ingestion_manifest,
    )

    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id="manifest-publish-guard")
        upsert_ingestion_manifest(conn, run.run_id, _manifest(**manifest_overrides))
        record_derived_stage_metadata(
            conn,
            run.run_id,
            _derived(universe_snapshot_id="manifest-publish-guard"),
        )
        transition_daily_run(conn, run.run_id, "evaluated")
        with pytest.raises(LedgerValidationError, match="manifest"):
            transition_daily_run(conn, run.run_id, "published")


@pytest.mark.parametrize(
    "metadata_patch",
    [
        {"computed_at": "not-a-timestamp"},
        {"available_at": "2099-03-02T20:02:00+00:00"},
        {"transformation_version": ""},
        {"source_run_ids": [" source-run "]},
        {"input_session": "2099-03-01"},
    ],
)
def test_database_publish_trigger_revalidates_canonical_stage_metadata(metadata_patch):
    from psycopg.types.json import Jsonb

    from daily_evaluation_ledger import (
        record_derived_stage_metadata,
        transition_daily_run,
        upsert_ingestion_manifest,
    )

    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id="db-canonical-stage-guard")
        upsert_ingestion_manifest(conn, run.run_id, _manifest())
        record_derived_stage_metadata(
            conn,
            run.run_id,
            _derived(universe_snapshot_id="db-canonical-stage-guard"),
        )
        transition_daily_run(conn, run.run_id, "evaluated")
        conn.execute(
            """
            UPDATE daily_evaluation_runs
            SET derived_stage_metadata =
                jsonb_set(derived_stage_metadata, '{features}',
                          derived_stage_metadata->'features' || %s)
            WHERE id=%s
            """,
            (Jsonb(metadata_patch), run.run_id),
        )
        with pytest.raises(Exception), conn.transaction():
            conn.execute(
                "UPDATE daily_evaluation_runs SET status='published' WHERE id=%s",
                (run.run_id,),
            )
