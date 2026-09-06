from __future__ import annotations

import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from test_db import resolve_test_dsn, test_connection

UTC = timezone.utc

# The ledger's canonical text contract is intentionally ASCII-only: every C0
# control, ordinary space, and DEL is forbidden at either edge. PostgreSQL
# text cannot represent NUL, so it is covered at the Python boundary only.
ASCII_EDGE_CHARS = tuple(chr(codepoint) for codepoint in range(33)) + ("\x7f",)
SQL_ASCII_EDGE_CHARS = tuple(chr(codepoint) for codepoint in range(1, 33)) + ("\x7f",)


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


def test_database_identity_vector_exactly_matches_python_canonical_json_hash():
    from daily_evaluation_ledger import DailyRunIdentity, _identity_key

    identity = DailyRunIdentity(
        target_session=date(2099, 12, 31),
        evaluator_name='daily "multi" \\ setup ☃',
        evaluator_version="v1\nβ",
        universe_snapshot_id="universe\t𐀀",
    )
    with test_connection() as conn:
        database_key = conn.execute(
            "SELECT wolfy_daily_run_identity(%s,%s,%s,%s)",
            (
                identity.target_session,
                identity.evaluator_name,
                identity.evaluator_version,
                identity.universe_snapshot_id,
            ),
        ).fetchone()[0]
    assert database_key == _identity_key(identity)


def test_database_rejects_arbitrary_valid_looking_run_identity_on_insert():
    with test_connection() as conn:
        with pytest.raises(Exception, match="run_identity"):
            conn.execute(
                """
                INSERT INTO daily_evaluation_runs(
                    id,run_identity,target_session,evaluator_name,evaluator_version,
                    universe_snapshot_id,required_stage_names
                ) VALUES (%s,%s,'2099-03-02','direct','1','direct',ARRAY['features'])
                """,
                (uuid.uuid4(), "f" * 64),
            )


@pytest.mark.parametrize(
    ("column", "value_sql"),
    [
        ("run_identity", "repeat('f',64)"),
        ("target_session", "target_session + 1"),
        ("evaluator_name", "evaluator_name || '-changed'"),
        ("evaluator_version", "evaluator_version || '-changed'"),
        ("universe_snapshot_id", "universe_snapshot_id || '-changed'"),
    ],
)
def test_database_freezes_run_identity_tuple_immediately_after_insert(column, value_sql):
    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id=f"immediate-identity-{column}")
        with pytest.raises(Exception, match="identity"):
            conn.execute(
                f"UPDATE daily_evaluation_runs SET {column}={value_sql} WHERE id=%s",
                (run.run_id,),
            )


def test_frozen_parent_session_preserves_existing_manifest_session_consistency():
    from daily_evaluation_ledger import upsert_ingestion_manifest

    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id="frozen-parent-manifest-session")
        manifest_id = upsert_ingestion_manifest(conn, run.run_id, _manifest())
        with pytest.raises(Exception, match="identity"), conn.transaction():
            conn.execute(
                "UPDATE daily_evaluation_runs SET target_session=target_session + 1 WHERE id=%s",
                (run.run_id,),
            )
        sessions = conn.execute(
            """
            SELECT run.target_session, manifest.target_session
            FROM daily_evaluation_runs AS run
            JOIN ingestion_run_manifests AS manifest ON manifest.run_id=run.id
            WHERE manifest.id=%s
            """,
            (manifest_id,),
        ).fetchone()
        assert sessions == (date(2099, 3, 2), date(2099, 3, 2))


@pytest.mark.parametrize("status", ["started", "data_incomplete", "evaluated", "failed"])
def test_database_identity_is_frozen_in_every_nonpublished_status(status):
    from daily_evaluation_ledger import transition_daily_run

    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id=f"identity-status-{status}")
        if status != "started":
            transition_daily_run(conn, run.run_id, status)
        with pytest.raises(Exception, match="identity"):
            conn.execute(
                "UPDATE daily_evaluation_runs SET target_session=target_session + 1 WHERE id=%s",
                (run.run_id,),
            )


@pytest.mark.parametrize(
    "status", ["started", "data_incomplete", "evaluated", "failed", "published"]
)
def test_database_freezes_required_stages_after_insert_in_every_status(status):
    from daily_evaluation_ledger import transition_daily_run

    with test_connection() as conn:
        universe = f"stage-contract-{status}"
        run = _create_run(conn, universe_snapshot_id=universe)
        if status == "published":
            _make_publishable(conn, run.run_id, universe_snapshot_id=universe)
        elif status != "started":
            transition_daily_run(conn, run.run_id, status)

        with pytest.raises(
            Exception, match="required stages|published.*immutable"
        ), conn.transaction():
            conn.execute(
                "UPDATE daily_evaluation_runs "
                "SET required_stage_names=ARRAY['ranking'] WHERE id=%s",
                (run.run_id,),
            )

        before = conn.execute(
            "SELECT updated_at FROM daily_evaluation_runs WHERE id=%s", (run.run_id,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE daily_evaluation_runs "
            "SET required_stage_names=required_stage_names WHERE id=%s",
            (run.run_id,),
        )
        rerun = _create_run(conn, universe_snapshot_id=universe)
        after = conn.execute(
            "SELECT updated_at FROM daily_evaluation_runs WHERE id=%s", (run.run_id,)
        ).fetchone()[0]
        assert rerun.run_id == run.run_id
        assert after == before


def test_python_rerun_still_rejects_distinct_required_stages():
    from daily_evaluation_ledger import LedgerValidationError

    with test_connection() as conn:
        _create_run(conn, universe_snapshot_id="stage-rerun-mismatch")
        with pytest.raises(LedgerValidationError, match="required_stages"):
            _create_run(
                conn,
                universe_snapshot_id="stage-rerun-mismatch",
                required_stages=("ranking",),
            )


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
        {"raw_payload_sha256": None, "immutable_object_ref": ""},
        {"raw_payload_sha256": None, "immutable_object_ref": "   "},
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
        "reason_codes": ("breakout_not_confirmed", "volume_failed"),
        "terminal_reason": "breakout_not_confirmed",
        "evaluated_at": _now(),
        "metrics": {"close": "101.25", "breakout_level": "102.00"},
        "gate_facts": {"breakout_not_confirmed": {"passed": False}},
        "source_fingerprint": "sha256:" + "c" * 64,
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
            _gate(
                reason_codes=("relative_strength_failed",),
                terminal_reason="relative_strength_failed",
                metrics={"rs": "0.01"},
            ),
        )
        row = conn.execute(
            """
            SELECT passed, reason_code_version, reason_codes, terminal_reason,
                   failed_gates, gate_facts, source_fingerprint, metrics, provenance
            FROM setup_gate_evaluations WHERE id=%s
            """,
            (first,),
        ).fetchone()
        assert first == second
        assert row == (
            False,
            1,
            ["relative_strength_failed"],
            "relative_strength_failed",
            ["relative_strength_failed"],
            {"breakout_not_confirmed": {"passed": False}},
            "sha256:" + "c" * 64,
            {"rs": "0.01"},
            {"feature_row_id": 42},
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"reason_code_version": 2},
        {"reason_codes": ("unknown_reason",)},
        {"reason_codes": ("volume_failed", "breakout_not_confirmed")},
        {"reason_codes": ("breakout_not_confirmed", "breakout_not_confirmed")},
        {"reason_codes": ("passed",), "passed": False, "terminal_reason": "passed"},
        {"reason_codes": ("trend_failed",), "passed": True, "terminal_reason": "trend_failed"},
        {"reason_codes": ("passed", "trend_failed"), "terminal_reason": "passed"},
        {"terminal_reason": "trend_failed"},
        {"ticker": "zzledger"},
        {"evaluated_at": datetime(2099, 3, 2, 20)},
        {"metrics": []},
        {"gate_facts": []},
        {"source_fingerprint": "   "},
        {"provenance": []},
    ],
)
def test_gate_evaluation_rejects_noncanonical_reasons_and_provenance(overrides):
    from daily_evaluation_ledger import LedgerValidationError, upsert_gate_evaluation

    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id=f"bad-gate-{len(str(overrides))}")
        with pytest.raises(LedgerValidationError):
            upsert_gate_evaluation(conn, run.run_id, _gate(**overrides))


CANONICAL_REASON_CODES = (
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
)


def test_python_reason_taxonomy_matches_the_exact_plan_contract():
    from daily_evaluation_ledger import CANONICAL_REASON_CODES as actual

    assert actual == {1: frozenset(CANONICAL_REASON_CODES)}


@pytest.mark.parametrize(
    ("passed", "version", "reasons", "metrics", "provenance"),
    [
        (False, 1, ["trend_failed", "liquidity_failed"], {}, {}),
        (False, 1, ["trend_failed", "trend_failed"], {}, {}),
        (False, 1, ["unknown_reason"], {}, {}),
        (False, 1, ["passed"], {}, {}),
        (True, 1, ["trend_failed"], {}, {}),
        (True, 1, ["passed", "trend_failed"], {}, {}),
        (False, 2, ["trend_failed"], {}, {}),
        (False, 1, ["trend_failed"], [], {}),
        (False, 1, ["trend_failed"], {}, []),
    ],
)
def test_database_rejects_noncanonical_gate_rows_from_direct_sql(
    passed, version, reasons, metrics, provenance
):
    from psycopg.types.json import Jsonb

    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id=f"direct-gate-{version}-{len(reasons)}")
        terminal_reason = reasons[0]
        with pytest.raises(Exception), conn.transaction():
            conn.execute(
                """
                INSERT INTO setup_gate_evaluations(
                    run_id,ticker,strategy,passed,reason_code_version,reason_codes,
                    terminal_reason,failed_gates,gate_facts,source_fingerprint,
                    evaluated_at,metrics,provenance
                ) VALUES (%s,'ZZDIRECT','direct_strategy',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    run.run_id,
                    passed,
                    version,
                    reasons,
                    terminal_reason,
                    Jsonb(reasons),
                    Jsonb({}),
                    "sha256:" + "d" * 64,
                    _now(),
                    Jsonb(metrics),
                    Jsonb(provenance),
                ),
            )


def test_database_accepts_only_the_canonical_pass_row_from_direct_sql():
    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id="direct-canonical-pass")
        conn.execute(
            """
            INSERT INTO setup_gate_evaluations(
                run_id,ticker,strategy,passed,reason_code_version,reason_codes,
                terminal_reason,failed_gates,gate_facts,source_fingerprint,
                evaluated_at,metrics,provenance
            ) VALUES (%s,'ZZPASS','direct_strategy',true,1,ARRAY['passed'],
                      'passed','[]'::jsonb,'{}'::jsonb,%s,%s,'{}'::jsonb,'{}'::jsonb)
            """,
            (run.run_id, "sha256:" + "e" * 64, _now()),
        )


@pytest.mark.parametrize(
    ("writer", "field"),
    [
        ("run", "evaluator_name"),
        ("run", "evaluator_version"),
        ("run", "universe_snapshot_id"),
        ("run", "required_stages"),
        ("manifest", "dataset"),
        ("manifest", "provider"),
        ("manifest", "source_endpoint"),
        ("manifest", "entitlement_class"),
        ("manifest", "delay_class"),
        ("manifest", "parser_version"),
        ("manifest", "schema_version"),
        ("manifest", "immutable_object_ref"),
        ("gate", "ticker"),
        ("gate", "strategy"),
        ("gate", "source_fingerprint"),
        ("derived", "stage_name"),
        ("derived", "transformation_version"),
        ("derived", "source_run_ids"),
        ("derived", "universe_snapshot_id"),
    ],
)
def test_python_ledger_text_rejects_every_ascii_control_or_space_at_edges(
    writer, field
):
    from daily_evaluation_ledger import (
        LedgerValidationError,
        record_derived_stage_metadata,
        upsert_gate_evaluation,
        upsert_ingestion_manifest,
    )

    with test_connection() as conn:
        run = _create_run(
            conn, universe_snapshot_id=f"ascii-python-{writer}-{field}-{uuid.uuid4().hex}"
        )
        for edge in ASCII_EDGE_CHARS:
            for invalid in (edge + "value", "value" + edge):
                with pytest.raises(LedgerValidationError):
                    if writer == "run":
                        overrides = {field: (invalid,) if field == "required_stages" else invalid}
                        values = {
                            "universe_snapshot_id": f"ascii-run-{uuid.uuid4().hex}"
                        }
                        values.update(overrides)
                        _create_run(conn, **values)
                    elif writer == "manifest":
                        overrides = {field: invalid}
                        if field == "immutable_object_ref":
                            overrides["raw_payload_sha256"] = None
                        upsert_ingestion_manifest(
                            conn, run.run_id, _manifest(**overrides)
                        )
                    elif writer == "gate":
                        value = invalid.upper() if field == "ticker" else invalid
                        upsert_gate_evaluation(conn, run.run_id, _gate(**{field: value}))
                    else:
                        value = (invalid,) if field == "source_run_ids" else invalid
                        record_derived_stage_metadata(
                            conn,
                            run.run_id,
                            _derived(**{field: value}),
                        )


@pytest.mark.parametrize("value", ["canonical", "with interior space", "\u00a0unicode\u00a0"])
def test_python_and_database_accept_same_canonical_ascii_text_boundaries(value):
    from daily_evaluation_ledger import _is_canonical_string

    with test_connection() as conn:
        database_result = conn.execute(
            "SELECT wolfy_is_canonical_ledger_text(%s)", (value,)
        ).fetchone()[0]
    assert _is_canonical_string(value) is database_result is True


@pytest.mark.parametrize("edge", SQL_ASCII_EDGE_CHARS)
def test_python_and_database_reject_same_ascii_text_boundaries(edge):
    from daily_evaluation_ledger import _is_canonical_string

    with test_connection() as conn:
        for invalid in (edge + "value", "value" + edge, edge):
            database_result = conn.execute(
                "SELECT wolfy_is_canonical_ledger_text(%s)", (invalid,)
            ).fetchone()[0]
            assert _is_canonical_string(invalid) is database_result is False


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("daily_evaluation_runs", "evaluator_name"),
        ("daily_evaluation_runs", "evaluator_version"),
        ("daily_evaluation_runs", "universe_snapshot_id"),
        ("ingestion_run_manifests", "dataset"),
        ("ingestion_run_manifests", "provider"),
        ("ingestion_run_manifests", "source_endpoint"),
        ("ingestion_run_manifests", "entitlement_class"),
        ("ingestion_run_manifests", "delay_class"),
        ("ingestion_run_manifests", "parser_version"),
        ("ingestion_run_manifests", "schema_version"),
        ("setup_gate_evaluations", "ticker"),
        ("setup_gate_evaluations", "strategy"),
        ("setup_gate_evaluations", "source_fingerprint"),
    ],
)
@pytest.mark.parametrize("invalid", ["", "\tvalue", "value\n", "\x01value", "value\x7f"])
def test_database_rejects_noncanonical_ledger_text_from_direct_sql(
    table, column, invalid
):
    from psycopg import sql

    from daily_evaluation_ledger import upsert_gate_evaluation, upsert_ingestion_manifest

    with test_connection() as conn:
        run = _create_run(
            conn, universe_snapshot_id=f"ascii-sql-{table}-{column}-{uuid.uuid4().hex}"
        )
        manifest_id = upsert_ingestion_manifest(conn, run.run_id, _manifest())
        gate_id = upsert_gate_evaluation(conn, run.run_id, _gate())
        row_id = {
            "daily_evaluation_runs": run.run_id,
            "ingestion_run_manifests": manifest_id,
            "setup_gate_evaluations": gate_id,
        }[table]
        candidate = invalid.upper() if column == "ticker" else invalid
        with pytest.raises(Exception), conn.transaction():
            conn.execute(
                sql.SQL("UPDATE {} SET {}=%s WHERE id=%s").format(
                    sql.Identifier(table), sql.Identifier(column)
                ),
                (candidate, row_id),
            )


@pytest.mark.parametrize("invalid", ["", "\tref", "ref\n", "\x01ref", "ref\x7f"])
def test_database_rejects_noncanonical_manifest_object_ref_from_direct_sql(invalid):
    with test_connection() as conn:
        run = _create_run(
            conn, universe_snapshot_id=f"ascii-object-ref-{uuid.uuid4().hex}"
        )
        manifest_id = conn.execute(
            """
            INSERT INTO ingestion_run_manifests(
                run_id,dataset,target_session,provider,source_endpoint,
                entitlement_class,delay_class,started_at,completed_at,
                expected_symbol_count,received_symbol_count,expected_row_count,
                received_row_count,retry_count,status,immutable_object_ref,
                parser_version,schema_version,quality_gate,provenance
            ) VALUES (%s,'prices','2099-03-02','provider','endpoint','free','t1',
                      %s,%s,1,1,1,1,0,'completed','canonical-ref','1','1','passed','{}')
            RETURNING id
            """,
            (run.run_id, _now(), _now()),
        ).fetchone()[0]
        with pytest.raises(Exception), conn.transaction():
            conn.execute(
                "UPDATE ingestion_run_manifests SET immutable_object_ref=%s WHERE id=%s",
                (invalid, manifest_id),
            )


@pytest.mark.parametrize(
    "invalid", ["", "\tfeatures", "features\n", "\x01features", "features\x7f"]
)
def test_database_rejects_noncanonical_required_stage_names_on_direct_insert(invalid):
    with test_connection() as conn:
        token = uuid.uuid4()
        evaluator = f"direct-stage-{token.hex}"
        with pytest.raises(Exception, match="noncanonical"), conn.transaction():
            conn.execute(
                """
                INSERT INTO daily_evaluation_runs(
                    id,run_identity,target_session,evaluator_name,evaluator_version,
                    universe_snapshot_id,required_stage_names
                ) VALUES (
                    %s,wolfy_daily_run_identity('2099-03-02',%s,'1','direct'),
                    '2099-03-02',%s,'1','direct',ARRAY[%s]
                )
                """,
                (token, evaluator, evaluator, invalid),
            )


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


def _stored_derived_payload(*, universe_snapshot_id="publish-ready", **overrides):
    payload = {
        "input_session": "2099-03-02",
        "computed_at": "2099-03-02T20:03:00+00:00",
        "available_at": "2099-03-02T20:04:00+00:00",
        "transformation_version": "feature-pipeline-5",
        "source_run_ids": ["massive-ingest-20990302"],
        "input_hash": "b" * 64,
        "universe_snapshot_id": universe_snapshot_id,
        "provenance": {"code_commit": "abc123"},
    }
    payload.update(overrides)
    return payload


def _make_publishable(conn, run_id, *, universe_snapshot_id="publish-ready"):
    from daily_evaluation_ledger import (
        record_derived_stage_metadata,
        transition_daily_run,
        upsert_ingestion_manifest,
    )

    upsert_ingestion_manifest(conn, run_id, _manifest())
    record_derived_stage_metadata(
        conn,
        run_id,
        _derived(universe_snapshot_id=universe_snapshot_id),
    )
    transition_daily_run(conn, run_id, "evaluated")
    transition_daily_run(conn, run_id, "published")


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


@pytest.mark.parametrize("status", ["started", "data_incomplete", "evaluated", "failed"])
def test_database_rejects_noncanonical_derived_metadata_in_every_nonpublished_status(
    status,
):
    from psycopg.types.json import Jsonb

    from daily_evaluation_ledger import transition_daily_run

    with test_connection() as conn:
        universe = f"derived-status-{status}"
        run = _create_run(conn, universe_snapshot_id=universe)
        if status != "started":
            transition_daily_run(conn, run.run_id, status)
        payload = _stored_derived_payload(
            universe_snapshot_id=universe,
            transformation_version="\tbad",
        )
        with pytest.raises(Exception, match="derived stage metadata"), conn.transaction():
            conn.execute(
                "UPDATE daily_evaluation_runs SET derived_stage_metadata=%s WHERE id=%s",
                (Jsonb({"features": payload}), run.run_id),
            )
        assert conn.execute(
            "SELECT derived_stage_metadata FROM daily_evaluation_runs WHERE id=%s",
            (run.run_id,),
        ).fetchone() == ({},)


@pytest.mark.parametrize(
    "metadata",
    [
        {"\tfeatures": _stored_derived_payload()},
        {"ranking": _stored_derived_payload()},
        {"features": []},
        {"features": {"transformation_version": "feature-pipeline-5"}},
        {"features": _stored_derived_payload(input_session="2099-02-30")},
        {"features": _stored_derived_payload(input_session="2099-03-01")},
        {"features": _stored_derived_payload(computed_at=123)},
        {"features": _stored_derived_payload(computed_at="2099-03-02 20:03:00+00:00")},
        {
            "features": _stored_derived_payload(
                computed_at="2099-03-02T20:05:00+00:00"
            )
        },
        {"features": _stored_derived_payload(transformation_version="bad\n")},
        {"features": _stored_derived_payload(transformation_version=True)},
        {"features": _stored_derived_payload(source_run_ids=[])},
        {"features": _stored_derived_payload(source_run_ids=[123])},
        {"features": _stored_derived_payload(source_run_ids=["source\r"])},
        {"features": _stored_derived_payload(source_run_ids=["source", "source"])},
        {"features": _stored_derived_payload(source_run_ids=["z-source", "a-source"])},
        {"features": _stored_derived_payload(input_hash="B" * 64)},
        {"features": _stored_derived_payload(universe_snapshot_id="other")},
        {"features": _stored_derived_payload(universe_snapshot_id="publish-ready\t")},
        {"features": _stored_derived_payload(provenance=[])},
        {
            "features": {
                **_stored_derived_payload(),
                "unexpected": "field",
            }
        },
    ],
)
def test_database_rejects_every_noncanonical_populated_derived_metadata_shape(metadata):
    from psycopg.types.json import Jsonb

    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id="publish-ready")
        with pytest.raises(Exception, match="derived stage metadata"):
            conn.execute(
                "UPDATE daily_evaluation_runs SET derived_stage_metadata=%s WHERE id=%s",
                (Jsonb(metadata), run.run_id),
            )


def test_database_rejects_noncanonical_derived_metadata_on_direct_insert():
    from psycopg.types.json import Jsonb

    from daily_evaluation_ledger import DailyRunIdentity, _identity_key

    identity = DailyRunIdentity(
        target_session=date(2099, 3, 2),
        evaluator_name="direct-derived-insert",
        evaluator_version="1",
        universe_snapshot_id="direct-derived-insert",
    )
    with test_connection() as conn:
        with pytest.raises(Exception, match="derived stage metadata"):
            conn.execute(
                """
                INSERT INTO daily_evaluation_runs(
                    id,run_identity,target_session,evaluator_name,evaluator_version,
                    universe_snapshot_id,required_stage_names,derived_stage_metadata
                ) VALUES (%s,%s,%s,%s,%s,%s,ARRAY['features'],%s)
                """,
                (
                    uuid.uuid4(),
                    _identity_key(identity),
                    identity.target_session,
                    identity.evaluator_name,
                    identity.evaluator_version,
                    identity.universe_snapshot_id,
                    Jsonb(
                        {
                            "features": _stored_derived_payload(
                                universe_snapshot_id=identity.universe_snapshot_id,
                                transformation_version="bad\t",
                            )
                        }
                    ),
                ),
            )


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
        {"source_run_ids": ("z-source", "a-source")},
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

        with pytest.raises(Exception), conn.transaction():
            conn.execute(
                """
                UPDATE daily_evaluation_runs
                SET derived_stage_metadata = '{"features": {}}'::jsonb
                WHERE id=%s
                """,
                (run.run_id,),
            )


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


@pytest.mark.parametrize("required_stages", [["features"], []])
def test_database_rejects_direct_insert_as_published_without_readiness(required_stages):
    import uuid

    with test_connection() as conn:
        token = uuid.uuid4()
        with pytest.raises(Exception), conn.transaction():
            conn.execute(
                """
                INSERT INTO daily_evaluation_runs(
                    id,run_identity,target_session,evaluator_name,evaluator_version,
                    universe_snapshot_id,required_stage_names,status
                ) VALUES (%s,%s,'2099-03-02','direct','1','direct',%s,'published')
                """,
                (token, token.hex, required_stages),
            )


@pytest.mark.parametrize(
    ("raw_hash", "object_ref"),
    [
        ("A" * 64, None),
        ("short", None),
        (None, ""),
        (None, "   "),
        (None, None),
        ("a" * 64, "s3://immutable/key"),
    ],
)
def test_database_rejects_noncanonical_manifest_payload_identity(raw_hash, object_ref):
    from psycopg.types.json import Jsonb

    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id=f"direct-manifest-{len(str(raw_hash))}")
        with pytest.raises(Exception), conn.transaction():
            conn.execute(
                """
                INSERT INTO ingestion_run_manifests(
                    run_id,dataset,target_session,provider,source_endpoint,
                    entitlement_class,delay_class,started_at,completed_at,
                    expected_symbol_count,received_symbol_count,expected_row_count,
                    received_row_count,retry_count,status,raw_payload_sha256,
                    immutable_object_ref,parser_version,schema_version,quality_gate,provenance
                ) VALUES (
                    %s,'prices','2099-03-02','provider','endpoint','free','t1',%s,%s,
                    1,1,1,1,0,'completed',%s,%s,'1','1','passed',%s
                )
                """,
                (run.run_id, _now(), _now(), raw_hash, object_ref, Jsonb({})),
            )


@pytest.mark.parametrize(
    "manifest_overrides",
    [
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


def test_database_rejects_manifest_target_session_that_differs_from_parent_run():
    from daily_evaluation_ledger import upsert_ingestion_manifest

    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id="manifest-session-guard")
        with pytest.raises(Exception, match="target_session must match parent run"):
            upsert_ingestion_manifest(
                conn,
                run.run_id,
                _manifest(target_session=date(2099, 3, 1)),
            )


@pytest.mark.parametrize(
    "metadata_patch",
    [
        {"computed_at": "not-a-timestamp"},
        {"available_at": "2099-03-02T20:02:00+00:00"},
        {"transformation_version": ""},
        {"source_run_ids": [" source-run "]},
        {"source_run_ids": ["z-source", "a-source"]},
        {"input_session": "2099-03-01"},
    ],
)
def test_database_write_trigger_rejects_noncanonical_stage_metadata_before_publication(
    metadata_patch,
):
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
        with pytest.raises(
            Exception, match="derived stage metadata"
        ), conn.transaction():
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
        transition_daily_run(conn, run.run_id, "published")
        assert conn.execute(
            "SELECT status FROM daily_evaluation_runs WHERE id=%s", (run.run_id,)
        ).fetchone() == ("published",)


@pytest.mark.parametrize(
    ("kind", "field"),
    [
        ("run", "target_session"),
        ("manifest", "target_session"),
        ("derived", "input_session"),
    ],
)
def test_date_only_fields_reject_datetime_without_touching_transaction(kind, field):
    from daily_evaluation_ledger import (
        DailyRunIdentity,
        LedgerValidationError,
        create_daily_run,
        record_derived_stage_metadata,
        upsert_ingestion_manifest,
    )

    with test_connection() as conn:
        universe = f"date-only-{kind}"
        run = _create_run(conn, universe_snapshot_id=universe)
        value = datetime(2099, 3, 2, tzinfo=UTC)
        with pytest.raises(LedgerValidationError, match="must be a date"):
            if kind == "run":
                create_daily_run(
                    conn,
                    DailyRunIdentity(
                        target_session=value,
                        evaluator_name="daily-multi-setup",
                        evaluator_version="1.0.0",
                        universe_snapshot_id="datetime-run",
                    ),
                )
            elif kind == "manifest":
                upsert_ingestion_manifest(conn, run.run_id, _manifest(**{field: value}))
            else:
                record_derived_stage_metadata(
                    conn,
                    run.run_id,
                    _derived(universe_snapshot_id=universe, **{field: value}),
                )
        assert conn.execute("SELECT 1").fetchone() == (1,)


@pytest.mark.parametrize(
    ("writer", "field"),
    [
        ("manifest", "provenance"),
        ("gate", "metrics"),
        ("gate", "gate_facts"),
        ("gate", "provenance"),
        ("derived", "provenance"),
    ],
)
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_json_mappings_reject_nonfinite_values_before_db(writer, field, invalid):
    from daily_evaluation_ledger import (
        LedgerValidationError,
        record_derived_stage_metadata,
        upsert_gate_evaluation,
        upsert_ingestion_manifest,
    )

    with test_connection() as conn:
        universe = f"json-{writer}-{field}-{invalid}"
        run = _create_run(conn, universe_snapshot_id=universe)
        payload = {"outer": [{"invalid": invalid}]}
        with pytest.raises(LedgerValidationError, match=field):
            if writer == "manifest":
                upsert_ingestion_manifest(conn, run.run_id, _manifest(**{field: payload}))
            elif writer == "gate":
                upsert_gate_evaluation(conn, run.run_id, _gate(**{field: payload}))
            else:
                record_derived_stage_metadata(
                    conn,
                    run.run_id,
                    _derived(universe_snapshot_id=universe, **{field: payload}),
                )
        assert conn.execute("SELECT 1").fetchone() == (1,)


def test_manifest_rejects_completion_before_start_without_touching_transaction():
    from daily_evaluation_ledger import LedgerValidationError, upsert_ingestion_manifest

    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id="manifest-chronology")
        with pytest.raises(LedgerValidationError, match="completed_at"):
            upsert_ingestion_manifest(
                conn, run.run_id, _manifest(completed_at=_now() - timedelta(seconds=1))
            )
        assert conn.execute("SELECT 1").fetchone() == (1,)


def test_database_rejects_manifest_completion_before_start():
    with test_connection() as conn:
        run = _create_run(conn, universe_snapshot_id="direct-manifest-chronology")
        with pytest.raises(Exception), conn.transaction():
            conn.execute(
                """
                INSERT INTO ingestion_run_manifests(
                    run_id,dataset,target_session,provider,source_endpoint,
                    entitlement_class,delay_class,started_at,completed_at,
                    expected_symbol_count,received_symbol_count,expected_row_count,
                    received_row_count,retry_count,status,raw_payload_sha256,
                    parser_version,schema_version,quality_gate,provenance
                ) VALUES (%s,'prices','2099-03-02','provider','endpoint','free','t1',
                          %s,%s,1,1,1,1,0,'completed',%s,'1','1','passed','{}')
                """,
                (run.run_id, _now(), _now() - timedelta(seconds=1), "f" * 64),
            )


@pytest.mark.parametrize("writer", ["manifest", "gate", "derived"])
def test_python_writers_reject_changes_after_publication(writer):
    from daily_evaluation_ledger import (
        LedgerValidationError,
        record_derived_stage_metadata,
        upsert_gate_evaluation,
        upsert_ingestion_manifest,
    )

    with test_connection() as conn:
        universe = f"published-python-{writer}"
        run = _create_run(conn, universe_snapshot_id=universe)
        _make_publishable(conn, run.run_id, universe_snapshot_id=universe)
        with pytest.raises(LedgerValidationError, match="published"):
            if writer == "manifest":
                upsert_ingestion_manifest(conn, run.run_id, _manifest(retry_count=2))
            elif writer == "gate":
                upsert_gate_evaluation(conn, run.run_id, _gate())
            else:
                record_derived_stage_metadata(
                    conn, run.run_id, _derived(universe_snapshot_id=universe)
                )


@pytest.mark.parametrize(
    "table",
    ["ingestion_run_manifests", "setup_gate_evaluations"],
)
@pytest.mark.parametrize("operation", ["insert", "update", "delete"])
def test_database_rejects_child_ledger_changes_after_publication(table, operation):
    from daily_evaluation_ledger import upsert_gate_evaluation

    with test_connection() as conn:
        universe = f"published-sql-{table}-{operation}"
        run = _create_run(conn, universe_snapshot_id=universe)
        gate_id = upsert_gate_evaluation(conn, run.run_id, _gate())
        _make_publishable(conn, run.run_id, universe_snapshot_id=universe)
        manifest_id = conn.execute(
            "SELECT id FROM ingestion_run_manifests WHERE run_id=%s", (run.run_id,)
        ).fetchone()[0]
        if table == "ingestion_run_manifests":
            statements = {
                "insert": (
                    "INSERT INTO ingestion_run_manifests(run_id,dataset,target_session,provider,source_endpoint,entitlement_class,delay_class,started_at,completed_at,expected_symbol_count,received_symbol_count,expected_row_count,received_row_count,retry_count,status,raw_payload_sha256,parser_version,schema_version,quality_gate,provenance) SELECT run_id,dataset,target_session,provider,source_endpoint || '-new',entitlement_class,delay_class,started_at,completed_at,expected_symbol_count,received_symbol_count,expected_row_count,received_row_count,retry_count,status,raw_payload_sha256,parser_version,schema_version,quality_gate,provenance FROM ingestion_run_manifests WHERE id=%s",
                    (manifest_id,),
                ),
                "update": ("UPDATE ingestion_run_manifests SET retry_count=retry_count+1 WHERE id=%s", (manifest_id,)),
                "delete": ("DELETE FROM ingestion_run_manifests WHERE id=%s", (manifest_id,)),
            }
        else:
            statements = {
                "insert": (
                    "INSERT INTO setup_gate_evaluations(run_id,ticker,strategy,passed,reason_code_version,reason_codes,terminal_reason,failed_gates,gate_facts,source_fingerprint,evaluated_at,metrics,provenance) VALUES (%s,'ZZNEW','strategy',false,1,ARRAY['trend_failed'],'trend_failed','[\"trend_failed\"]','{}','fingerprint',%s,'{}','{}')",
                    (run.run_id, _now()),
                ),
                "update": ("UPDATE setup_gate_evaluations SET evaluated_at=evaluated_at + interval '1 second' WHERE id=%s", (gate_id,)),
                "delete": ("DELETE FROM setup_gate_evaluations WHERE id=%s", (gate_id,)),
            }
        sql, params = statements[operation]
        with pytest.raises(Exception, match="published"), conn.transaction():
            conn.execute(sql, params)


def test_database_rejects_derived_metadata_change_after_publication():
    with test_connection() as conn:
        universe = "published-sql-derived"
        run = _create_run(conn, universe_snapshot_id=universe)
        _make_publishable(conn, run.run_id, universe_snapshot_id=universe)
        with pytest.raises(Exception, match="published"), conn.transaction():
            conn.execute(
                "UPDATE daily_evaluation_runs SET derived_stage_metadata=jsonb_set(derived_stage_metadata,'{features,transformation_version}','\"changed\"') WHERE id=%s",
                (run.run_id,),
            )


@pytest.mark.parametrize(
    ("column", "value_sql"),
    [
        ("id", "gen_random_uuid()"),
        ("run_identity", "run_identity || '-changed'"),
        ("target_session", "target_session + 1"),
        ("evaluator_name", "evaluator_name || '-changed'"),
        ("evaluator_version", "evaluator_version || '-changed'"),
        ("universe_snapshot_id", "universe_snapshot_id || '-changed'"),
        ("required_stage_names", "ARRAY['other']::text[]"),
        ("derived_stage_metadata", "'{}'::jsonb"),
        ("created_at", "created_at + interval '1 second'"),
        ("updated_at", "updated_at + interval '1 second'"),
    ],
)
def test_database_rejects_published_parent_identity_readiness_and_audit_updates(
    column, value_sql
):
    with test_connection() as conn:
        universe = f"published-parent-{column}"
        run = _create_run(conn, universe_snapshot_id=universe)
        _make_publishable(conn, run.run_id, universe_snapshot_id=universe)
        with pytest.raises(Exception, match="published"), conn.transaction():
            conn.execute(
                f"UPDATE daily_evaluation_runs SET {column}={value_sql} WHERE id=%s",
                (run.run_id,),
            )


def test_database_published_parent_exact_noop_preserves_audit_timestamp():
    with test_connection() as conn:
        universe = "published-parent-noop"
        run = _create_run(conn, universe_snapshot_id=universe)
        _make_publishable(conn, run.run_id, universe_snapshot_id=universe)
        before = conn.execute(
            "SELECT updated_at FROM daily_evaluation_runs WHERE id=%s", (run.run_id,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE daily_evaluation_runs SET status=status WHERE id=%s", (run.run_id,)
        )
        after = conn.execute(
            "SELECT updated_at FROM daily_evaluation_runs WHERE id=%s", (run.run_id,)
        ).fetchone()[0]
        assert after == before


def test_database_rejects_published_parent_delete_without_cascading_children():
    from daily_evaluation_ledger import upsert_gate_evaluation

    with test_connection() as conn:
        universe = "published-parent-delete"
        run = _create_run(conn, universe_snapshot_id=universe)
        upsert_gate_evaluation(conn, run.run_id, _gate())
        _make_publishable(conn, run.run_id, universe_snapshot_id=universe)
        before = conn.execute(
            "SELECT (SELECT count(*) FROM ingestion_run_manifests WHERE run_id=%s), "
            "(SELECT count(*) FROM setup_gate_evaluations WHERE run_id=%s)",
            (run.run_id, run.run_id),
        ).fetchone()
        with pytest.raises(Exception, match="published"), conn.transaction():
            conn.execute("DELETE FROM daily_evaluation_runs WHERE id=%s", (run.run_id,))
        after = conn.execute(
            "SELECT (SELECT count(*) FROM ingestion_run_manifests WHERE run_id=%s), "
            "(SELECT count(*) FROM setup_gate_evaluations WHERE run_id=%s)",
            (run.run_id, run.run_id),
        ).fetchone()
        assert after == before == (1, 1)


@pytest.mark.parametrize("table", ["ingestion_run_manifests", "setup_gate_evaluations"])
@pytest.mark.parametrize("published_side", ["old", "new"])
def test_database_rejects_child_reparenting_from_or_to_published_run(
    table, published_side
):
    from daily_evaluation_ledger import upsert_gate_evaluation, upsert_ingestion_manifest

    with test_connection() as conn:
        published_universe = f"published-reparent-{table}-{published_side}"
        published = _create_run(conn, universe_snapshot_id=published_universe)
        other = _create_run(conn, universe_snapshot_id=f"other-{table}-{published_side}")
        source = published if published_side == "old" else other
        if table == "ingestion_run_manifests":
            child_id = upsert_ingestion_manifest(conn, source.run_id, _manifest())
        else:
            child_id = upsert_gate_evaluation(conn, source.run_id, _gate())
        _make_publishable(conn, published.run_id, universe_snapshot_id=published_universe)
        destination = other if published_side == "old" else published
        with pytest.raises(Exception, match="published"), conn.transaction():
            conn.execute(
                f"UPDATE {table} SET run_id=%s WHERE id=%s",
                (destination.run_id, child_id),
            )


def _wait_for_lock(conn, pid: int, *, locktype: str | None = None) -> tuple[str, str]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        row = conn.execute(
            "SELECT wait_event_type,wait_event FROM pg_stat_activity WHERE pid=%s",
            (pid,),
        ).fetchone()
        if row and row[0] == "Lock" and (locktype is None or row[1] == locktype):
            return row
        threading.Event().wait(0.01)
    pytest.fail(f"backend {pid} did not expose expected lock wait")


def test_writer_waiting_behind_publication_observes_published_and_fails_closed():
    import psycopg

    from daily_evaluation_ledger import (
        LedgerValidationError,
        record_derived_stage_metadata,
        transition_daily_run,
        upsert_ingestion_manifest,
    )

    dsn = resolve_test_dsn()
    setup = psycopg.connect(dsn, autocommit=True)
    publisher = psycopg.connect(dsn)
    writer = psycopg.connect(dsn)
    run = None
    try:
        universe = f"publication-race-{uuid.uuid4().hex}"
        run = _create_run(setup, universe_snapshot_id=universe)
        upsert_ingestion_manifest(setup, run.run_id, _manifest())
        record_derived_stage_metadata(
            setup, run.run_id, _derived(universe_snapshot_id=universe)
        )
        transition_daily_run(setup, run.run_id, "evaluated")
        publisher.execute(
            "UPDATE daily_evaluation_runs SET status='published' WHERE id=%s",
            (run.run_id,),
        )
        result = {}

        def write_manifest():
            try:
                upsert_ingestion_manifest(writer, run.run_id, _manifest(retry_count=9))
            except Exception as exc:  # asserted across the thread boundary
                result["error"] = exc

        thread = threading.Thread(target=write_manifest)
        thread.start()
        assert _wait_for_lock(setup, writer.info.backend_pid)[0] == "Lock"
        assert thread.is_alive(), "writer must wait for the publisher's parent-row lock"
        publisher.commit()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert isinstance(result.get("error"), LedgerValidationError)
        assert "published" in str(result["error"])
    finally:
        publisher.rollback()
        writer.rollback()
        if run is not None:
            with setup.transaction():
                setup.execute(
                    "ALTER TABLE daily_evaluation_runs DISABLE TRIGGER "
                    "trg_daily_evaluation_run_transition"
                )
                setup.execute(
                    "ALTER TABLE ingestion_run_manifests DISABLE TRIGGER "
                    "trg_immutable_published_manifest"
                )
                setup.execute(
                    "ALTER TABLE setup_gate_evaluations DISABLE TRIGGER "
                    "trg_immutable_published_gate"
                )
                try:
                    setup.execute(
                        "DELETE FROM daily_evaluation_runs WHERE id=%s", (run.run_id,)
                    )
                finally:
                    setup.execute(
                        "ALTER TABLE daily_evaluation_runs ENABLE TRIGGER "
                        "trg_daily_evaluation_run_transition"
                    )
                    setup.execute(
                        "ALTER TABLE ingestion_run_manifests ENABLE TRIGGER "
                        "trg_immutable_published_manifest"
                    )
                    setup.execute(
                        "ALTER TABLE setup_gate_evaluations ENABLE TRIGGER "
                        "trg_immutable_published_gate"
                    )
        setup.close()
        publisher.close()
        writer.close()


def _task3_schema_sql() -> str:
    schema = (Path(__file__).resolve().parent / "postgres_init.sql").read_text()
    return schema[schema.index("-- Task 3: atomic") :]


def _create_partial_task3_schema(
    conn,
    schema_name: str,
    *,
    gate_overrides: dict[str, object] | None = None,
    run_overrides: dict[str, object] | None = None,
    manifest_overrides: dict[str, object] | None = None,
):
    from psycopg import sql
    from psycopg.types.json import Jsonb

    conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    conn.execute(
        sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema_name))
    )
    conn.execute(
        """
        CREATE TABLE daily_evaluation_runs (
            id UUID PRIMARY KEY, run_identity TEXT NOT NULL UNIQUE,
            target_session DATE NOT NULL, evaluator_name TEXT NOT NULL,
            evaluator_version TEXT NOT NULL, universe_snapshot_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'started', created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(target_session,evaluator_name,evaluator_version,universe_snapshot_id)
        );
        CREATE TABLE ingestion_run_manifests (
            id BIGSERIAL PRIMARY KEY, run_id UUID NOT NULL REFERENCES daily_evaluation_runs(id),
            dataset TEXT NOT NULL, target_session DATE NOT NULL, provider TEXT NOT NULL,
            source_endpoint TEXT NOT NULL, entitlement_class TEXT NOT NULL,
            delay_class TEXT NOT NULL, started_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ, expected_symbol_count INTEGER NOT NULL,
            received_symbol_count INTEGER NOT NULL, expected_row_count BIGINT NOT NULL,
            received_row_count BIGINT NOT NULL, retry_count INTEGER NOT NULL,
            status TEXT NOT NULL, raw_payload_sha256 TEXT, parser_version TEXT NOT NULL,
            schema_version TEXT NOT NULL, quality_gate TEXT NOT NULL
        );
        CREATE TABLE setup_gate_evaluations (
            id BIGSERIAL PRIMARY KEY, run_id UUID NOT NULL REFERENCES daily_evaluation_runs(id),
            ticker TEXT NOT NULL, strategy TEXT NOT NULL, passed BOOLEAN NOT NULL,
            reason_code_version INTEGER NOT NULL, reason_codes TEXT[] NOT NULL,
            terminal_reason TEXT, failed_gates JSONB, gate_facts JSONB,
            source_fingerprint TEXT, evaluated_at TIMESTAMPTZ NOT NULL,
            metrics JSONB NOT NULL DEFAULT '{}', provenance JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(run_id,ticker,strategy)
        )
        """
    )
    from daily_evaluation_ledger import DailyRunIdentity, _identity_key

    run_id = uuid.uuid4()
    run_identity = _identity_key(
        DailyRunIdentity(
            target_session=date(2099, 3, 2),
            evaluator_name="legacy",
            evaluator_version="1",
            universe_snapshot_id="legacy-universe",
        )
    )
    conn.execute(
        "INSERT INTO daily_evaluation_runs(id,run_identity,target_session,evaluator_name,evaluator_version,universe_snapshot_id) VALUES (%s,%s,'2099-03-02','legacy','1','legacy-universe')",
        (run_id, run_identity),
    )
    if run_overrides:
        if "required_stage_names" in run_overrides:
            conn.execute("ALTER TABLE daily_evaluation_runs ADD COLUMN required_stage_names TEXT[]")
        if "derived_stage_metadata" in run_overrides:
            conn.execute("ALTER TABLE daily_evaluation_runs ADD COLUMN derived_stage_metadata JSONB")
        assignments = []
        values = []
        for column, value in run_overrides.items():
            assignments.append(sql.SQL("{} = %s").format(sql.Identifier(column)))
            values.append(Jsonb(value) if column == "derived_stage_metadata" else value)
        values.append(run_id)
        conn.execute(
            sql.SQL("UPDATE daily_evaluation_runs SET {} WHERE id = %s").format(
                sql.SQL(", ").join(assignments)
            ),
            values,
        )
    conn.execute(
        """
        INSERT INTO ingestion_run_manifests(
            run_id,dataset,target_session,provider,source_endpoint,entitlement_class,
            delay_class,started_at,completed_at,expected_symbol_count,received_symbol_count,
            expected_row_count,received_row_count,retry_count,status,raw_payload_sha256,
            parser_version,schema_version,quality_gate
        ) VALUES (%s,'prices','2099-03-02','provider','endpoint','free','t1',%s,%s,
                  1,1,1,1,0,'completed',%s,'1','1','passed')
        """,
        (run_id, _now(), _now(), "a" * 64),
    )
    if manifest_overrides:
        if "immutable_object_ref" in manifest_overrides:
            conn.execute(
                "ALTER TABLE ingestion_run_manifests ADD COLUMN immutable_object_ref TEXT"
            )
        if "provenance" in manifest_overrides:
            conn.execute("ALTER TABLE ingestion_run_manifests ADD COLUMN provenance JSONB")
        if "created_at" in manifest_overrides:
            conn.execute(
                "ALTER TABLE ingestion_run_manifests ADD COLUMN created_at TIMESTAMPTZ"
            )
        if "updated_at" in manifest_overrides:
            conn.execute(
                "ALTER TABLE ingestion_run_manifests ADD COLUMN updated_at TIMESTAMPTZ"
            )
        assignments = []
        values = []
        for column, value in manifest_overrides.items():
            assignments.append(sql.SQL("{} = %s").format(sql.Identifier(column)))
            values.append(Jsonb(value) if column == "provenance" else value)
        values.append(run_id)
        conn.execute(
            sql.SQL("UPDATE ingestion_run_manifests SET {} WHERE run_id = %s").format(
                sql.SQL(", ").join(assignments)
            ),
            values,
        )
    gate = {
        "ticker": "ZZLEGACY",
        "strategy": "legacy",
        "passed": False,
        "reason_code_version": 1,
        "reason_codes": ["trend_failed"],
        "terminal_reason": None,
        "failed_gates": None,
        "gate_facts": {},
        "source_fingerprint": "legacy-fingerprint",
        "metrics": {},
        "provenance": {},
    }
    gate.update(gate_overrides or {})
    conn.execute(
        """
        INSERT INTO setup_gate_evaluations(
            run_id,ticker,strategy,passed,reason_code_version,reason_codes,
            terminal_reason,failed_gates,gate_facts,source_fingerprint,evaluated_at,
            metrics,provenance
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            run_id,
            gate["ticker"],
            gate["strategy"],
            gate["passed"],
            gate["reason_code_version"],
            gate["reason_codes"],
            gate["terminal_reason"],
            None if gate["failed_gates"] is None else Jsonb(gate["failed_gates"]),
            Jsonb(gate["gate_facts"]),
            gate["source_fingerprint"],
            _now(),
            Jsonb(gate["metrics"]),
            Jsonb(gate["provenance"]),
        ),
    )
    return run_id


def _partial_task3_snapshot(conn):
    columns = conn.execute(
        "SELECT table_name,column_name,data_type,is_nullable,column_default "
        "FROM information_schema.columns WHERE table_schema=current_schema() "
        "AND table_name IN ('daily_evaluation_runs','ingestion_run_manifests') "
        "ORDER BY table_name,ordinal_position"
    ).fetchall()
    constraints = conn.execute(
        "SELECT c.relname,con.conname,pg_get_constraintdef(con.oid) "
        "FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=current_schema() AND c.relname IN "
        "('daily_evaluation_runs','ingestion_run_manifests') "
        "ORDER BY c.relname,con.conname"
    ).fetchall()
    runs = conn.execute(
        "SELECT to_jsonb(r) FROM daily_evaluation_runs r ORDER BY id"
    ).fetchall()
    manifests = conn.execute(
        "SELECT to_jsonb(m) FROM ingestion_run_manifests m ORDER BY id"
    ).fetchall()
    return columns, constraints, runs, manifests


@pytest.mark.parametrize(
    "run_overrides",
    [
        {"status": "complete"},
        {"run_identity": " legacy "},
        {"run_identity": "f" * 64},
        {"evaluator_name": ""},
        {"evaluator_name": "\tevaluator"},
        {"evaluator_version": " 1"},
        {"evaluator_version": "1\n"},
        {"universe_snapshot_id": "   "},
        {"universe_snapshot_id": "\x01universe"},
        {"required_stage_names": []},
        {"required_stage_names": ["features", "features"]},
        {"required_stage_names": [" features"]},
        {"required_stage_names": ["features\x7f"]},
        {"required_stage_names": ["ranking", "features"]},
        {"required_stage_names": [None]},
        {"derived_stage_metadata": []},
        {
            "derived_stage_metadata": {
                "features": _stored_derived_payload(
                    universe_snapshot_id="legacy-universe",
                    transformation_version="bad\n",
                )
            }
        },
        {"updated_at": datetime(2000, 1, 1, tzinfo=UTC)},
    ],
)
def test_task3_schema_rejects_noncanonical_populated_partial_run_atomically(
    run_overrides,
):
    import psycopg
    from psycopg import sql

    with psycopg.connect(resolve_test_dsn(), autocommit=True) as conn:
        schema_name = f"task3_bad_run_{uuid.uuid4().hex}"
        try:
            _create_partial_task3_schema(conn, schema_name, run_overrides=run_overrides)
            before = _partial_task3_snapshot(conn)
            with pytest.raises(Exception, match="cannot migrate legacy daily_evaluation_runs"):
                conn.execute(_task3_schema_sql())
            conn.rollback()
            assert _partial_task3_snapshot(conn) == before
            assert conn.execute(
                """
                SELECT count(*)
                FROM pg_proc AS procedure
                JOIN pg_namespace AS namespace ON namespace.oid=procedure.pronamespace
                WHERE namespace.nspname=%s
                  AND procedure.proname IN (
                      'wolfy_python_json_string', 'wolfy_daily_run_identity',
                      'wolfy_is_canonical_ledger_text',
                      'wolfy_is_valid_derived_stage_metadata'
                  )
                """,
                (schema_name,),
            ).fetchone() == (0,)
        finally:
            conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )


@pytest.mark.parametrize(
    "manifest_overrides",
    [
        {"dataset": ""},
        {"dataset": "\tdataset"},
        {"provider": " provider "},
        {"provider": "provider\n"},
        {"source_endpoint": "   "},
        {"entitlement_class": " free"},
        {"delay_class": "t1 "},
        {"parser_version": ""},
        {"schema_version": " 1 "},
        {"target_session": date(2099, 3, 1)},
        {"expected_symbol_count": -1},
        {"received_symbol_count": -1},
        {"expected_row_count": -1},
        {"received_row_count": -1},
        {"retry_count": -1},
        {"status": "complete"},
        {"quality_gate": "ok"},
        {"completed_at": None},
        {"completed_at": _now() - timedelta(seconds=1)},
        {"provenance": []},
        {"raw_payload_sha256": "A" * 64},
        {"raw_payload_sha256": None},
        {"immutable_object_ref": "   ", "raw_payload_sha256": None},
        {"immutable_object_ref": " s3://bucket/key ", "raw_payload_sha256": None},
        {"immutable_object_ref": "\x01s3://bucket/key", "raw_payload_sha256": None},
        {"immutable_object_ref": "s3://bucket/key"},
        {"created_at": _now(), "updated_at": _now() - timedelta(seconds=1)},
    ],
)
def test_task3_schema_rejects_noncanonical_populated_partial_manifest_atomically(
    manifest_overrides,
):
    import psycopg
    from psycopg import sql

    with psycopg.connect(resolve_test_dsn(), autocommit=True) as conn:
        schema_name = f"task3_bad_manifest_{uuid.uuid4().hex}"
        try:
            _create_partial_task3_schema(
                conn, schema_name, manifest_overrides=manifest_overrides
            )
            before = _partial_task3_snapshot(conn)
            with pytest.raises(
                Exception, match="cannot migrate legacy ingestion_run_manifests"
            ):
                conn.execute(_task3_schema_sql())
            conn.rollback()
            assert _partial_task3_snapshot(conn) == before
        finally:
            conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )


def test_task3_schema_migrates_populated_partial_schema_twice_without_data_loss():
    import psycopg
    from psycopg import sql

    with psycopg.connect(resolve_test_dsn(), autocommit=True) as conn:
        schema_name = f"task3_upgrade_{uuid.uuid4().hex}"
        try:
            run_id = _create_partial_task3_schema(conn, schema_name)
            conn.execute(_task3_schema_sql())
            conn.execute(_task3_schema_sql())
            gate = conn.execute(
                "SELECT terminal_reason,failed_gates,gate_facts,source_fingerprint FROM setup_gate_evaluations WHERE run_id=%s",
                (run_id,),
            ).fetchone()
            manifest = conn.execute(
                "SELECT immutable_object_ref,provenance FROM ingestion_run_manifests WHERE run_id=%s",
                (run_id,),
            ).fetchone()
            daily = conn.execute(
                "SELECT required_stage_names,derived_stage_metadata FROM daily_evaluation_runs WHERE id=%s",
                (run_id,),
            ).fetchone()
            assert gate == ("trend_failed", ["trend_failed"], {}, "legacy-fingerprint")
            assert manifest == (None, {})
            assert daily == (["features"], {})
            canonical_constraints = {
                row[0]
                for row in conn.execute(
                    "SELECT conname FROM pg_constraint WHERE conrelid IN "
                    "('daily_evaluation_runs'::regclass,'ingestion_run_manifests'::regclass,"
                    "'setup_gate_evaluations'::regclass)"
                ).fetchall()
            }
            assert {
                "daily_evaluation_runs_status_check",
                "daily_evaluation_runs_identity_contract_check",
                "daily_evaluation_runs_stage_metadata_check",
                "daily_evaluation_runs_chronology_check",
                "daily_evaluation_runs_run_identity_canonical_key",
                "daily_evaluation_runs_identity_tuple_canonical_key",
                "ingestion_run_manifests_payload_identity_check",
                "ingestion_run_manifests_chronology_check",
                "ingestion_run_manifests_contract_check",
                "ingestion_run_manifests_identity_canonical_key",
                "setup_gate_evaluations_text_contract_check",
            } <= canonical_constraints
            assert conn.execute("SELECT count(*) FROM setup_gate_evaluations").fetchone() == (
                1,
            )
            for statement in (
                "UPDATE daily_evaluation_runs SET required_stage_names=ARRAY['ranking'] WHERE id=%s",
                "UPDATE ingestion_run_manifests SET dataset=E'\\tdataset' WHERE run_id=%s",
                "UPDATE setup_gate_evaluations SET ticker=E'\\tZZLEGACY' WHERE run_id=%s",
            ):
                with pytest.raises(Exception), conn.transaction():
                    conn.execute(statement, (run_id,))
        finally:
            conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )


def test_task3_schema_preserves_valid_populated_derived_metadata():
    import psycopg
    from psycopg import sql

    metadata = {
        "features": _stored_derived_payload(universe_snapshot_id="legacy-universe")
    }
    with psycopg.connect(resolve_test_dsn(), autocommit=True) as conn:
        schema_name = f"task3_valid_derived_{uuid.uuid4().hex}"
        try:
            run_id = _create_partial_task3_schema(
                conn,
                schema_name,
                run_overrides={"derived_stage_metadata": metadata},
            )
            conn.execute(_task3_schema_sql())
            assert conn.execute(
                "SELECT derived_stage_metadata FROM daily_evaluation_runs WHERE id=%s",
                (run_id,),
            ).fetchone() == (metadata,)
        finally:
            conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )


@pytest.mark.parametrize(
    "mutation",
    [
        "status='complete'",
        "run_identity=' legacy '",
        "evaluator_name=''",
        "evaluator_version=' 1'",
        "universe_snapshot_id='   '",
        "required_stage_names=ARRAY[]::text[]",
        "required_stage_names=ARRAY['features','features']",
        "required_stage_names=ARRAY[' features']",
        "required_stage_names=ARRAY['ranking','features']",
        "required_stage_names=ARRAY[NULL]::text[]",
        "derived_stage_metadata='[]'::jsonb",
        "created_at=updated_at + interval '1 second'",
    ],
)
def test_task3_upgraded_partial_run_rejects_future_direct_sql_bypasses(mutation):
    import psycopg
    from psycopg import sql

    with psycopg.connect(resolve_test_dsn(), autocommit=True) as conn:
        schema_name = f"task3_run_guard_{uuid.uuid4().hex}"
        try:
            run_id = _create_partial_task3_schema(conn, schema_name)
            conn.execute(_task3_schema_sql())
            with pytest.raises(Exception), conn.transaction():
                conn.execute(
                    f"UPDATE daily_evaluation_runs SET {mutation} WHERE id=%s",
                    (run_id,),
                )
        finally:
            conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )


@pytest.mark.parametrize(
    "mutation",
    [
        "dataset=''",
        "provider=' provider '",
        "source_endpoint='   '",
        "entitlement_class=' free'",
        "delay_class='t1 '",
        "parser_version=''",
        "schema_version=' 1 '",
        "target_session=DATE '2099-03-01'",
        "expected_symbol_count=-1",
        "received_symbol_count=-1",
        "expected_row_count=-1",
        "received_row_count=-1",
        "retry_count=-1",
        "status='complete'",
        "quality_gate='ok'",
        "completed_at=NULL",
        "completed_at=started_at - interval '1 second'",
        "provenance='[]'::jsonb",
        "raw_payload_sha256=repeat('A',64)",
        "raw_payload_sha256=NULL",
        "immutable_object_ref='s3://bucket/key'",
        "raw_payload_sha256=NULL,immutable_object_ref='   '",
        "raw_payload_sha256=NULL,immutable_object_ref=' s3://bucket/key '",
        "created_at=updated_at + interval '1 second'",
    ],
)
def test_task3_upgraded_partial_manifest_rejects_future_direct_sql_bypasses(mutation):
    import psycopg
    from psycopg import sql

    with psycopg.connect(resolve_test_dsn(), autocommit=True) as conn:
        schema_name = f"task3_manifest_guard_{uuid.uuid4().hex}"
        try:
            run_id = _create_partial_task3_schema(conn, schema_name)
            conn.execute(_task3_schema_sql())
            with pytest.raises(Exception), conn.transaction():
                conn.execute(
                    f"UPDATE ingestion_run_manifests SET {mutation} WHERE run_id=%s",
                    (run_id,),
                )
        finally:
            conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )


@pytest.mark.parametrize(
    "gate_overrides",
    [
        {"reason_code_version": 2},
        {"reason_codes": ["volume_failed", "trend_failed"]},
        {"reason_codes": ["trend_failed", "trend_failed"]},
        {"reason_codes": ["invented_reason"]},
        {"passed": True, "reason_codes": ["trend_failed"]},
        {"terminal_reason": "volume_failed"},
        {"failed_gates": ["volume_failed"]},
        {"gate_facts": []},
        {"source_fingerprint": " fingerprint "},
        {"source_fingerprint": "fingerprint\x7f"},
        {"ticker": ""},
        {"ticker": "\tZZLEGACY"},
        {"ticker": "zzlegacy"},
        {"strategy": ""},
        {"strategy": "legacy\n"},
        {"metrics": []},
        {"provenance": []},
        {"reason_codes": ["trend_failed", "volume_failed"]},
    ],
)
def test_task3_schema_fails_closed_for_every_noncanonical_legacy_gate_row(
    gate_overrides,
):
    import psycopg
    from psycopg import sql

    with psycopg.connect(resolve_test_dsn(), autocommit=True) as conn:
        schema_name = f"task3_invalid_{uuid.uuid4().hex}"
        try:
            _create_partial_task3_schema(conn, schema_name, gate_overrides=gate_overrides)
            with pytest.raises(
                Exception, match="cannot migrate legacy setup_gate_evaluations"
            ):
                conn.execute(_task3_schema_sql())
            # A failed explicit migration transaction remains aborted until the
            # psql client rolls it back (or disconnects with ON_ERROR_STOP).
            conn.rollback()
            columns = conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema=%s AND table_name='daily_evaluation_runs' "
                "AND column_name IN ('required_stage_names','derived_stage_metadata')",
                (schema_name,),
            ).fetchall()
            assert columns == []
            row = conn.execute(
                "SELECT terminal_reason,failed_gates FROM setup_gate_evaluations"
            ).fetchone()
            assert row == (
                gate_overrides.get("terminal_reason"),
                gate_overrides.get("failed_gates"),
            )
        finally:
            conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )


def test_task3_schema_serializes_concurrent_normal_psql_migrations():
    import psycopg
    from psycopg import sql

    dsn = resolve_test_dsn()
    schema_name = f"task3_concurrent_{uuid.uuid4().hex}"
    with psycopg.connect(dsn, autocommit=True) as setup:
        _create_partial_task3_schema(setup, schema_name)
        blocker = psycopg.connect(dsn)
        migrators = [psycopg.connect(dsn, autocommit=True) for _ in range(2)]
        errors: list[Exception] = []
        try:
            blocker.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended('wolfy_task3_migration', 0))"
            )
            for conn in migrators:
                conn.execute(
                    sql.SQL("SET search_path TO {}, public").format(
                        sql.Identifier(schema_name)
                    )
                )

            def migrate(conn):
                try:
                    conn.execute(_task3_schema_sql())
                except Exception as exc:  # asserted across the thread boundary
                    errors.append(exc)

            threads = [
                threading.Thread(target=migrate, args=(conn,)) for conn in migrators
            ]
            for thread in threads:
                thread.start()
            for conn in migrators:
                assert _wait_for_lock(
                    setup, conn.info.backend_pid, locktype="advisory"
                ) == ("Lock", "advisory")
            blocker.commit()
            for thread in threads:
                thread.join(timeout=10)
                assert not thread.is_alive()
            assert errors == []
            assert setup.execute(
                sql.SQL("SELECT count(*) FROM {}.setup_gate_evaluations").format(
                    sql.Identifier(schema_name)
                )
            ).fetchone() == (1,)
        finally:
            blocker.rollback()
            blocker.close()
            for conn in migrators:
                conn.close()
            setup.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
