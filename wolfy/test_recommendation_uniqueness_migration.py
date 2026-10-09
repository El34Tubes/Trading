from __future__ import annotations

import threading
import uuid
from pathlib import Path

import pytest
from psycopg import sql

from test_db import resolve_test_dsn


MIGRATION = (
    Path(__file__).with_name("migrations")
    / "20260917_recommendation_uniqueness.sql"
)
ACTIVE_STATUSES = ("paper_candidate", "paper_logged")


def _migration_sql() -> str:
    return MIGRATION.read_text()


def _create_recommendations(conn, schema_name: str) -> None:
    conn.execute(
        sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
    )
    conn.execute(
        sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema_name))
    )
    conn.execute(
        """CREATE TABLE recommendations (
               id bigserial PRIMARY KEY,
               ticker text NOT NULL,
               recommendation_type text NOT NULL,
               status text NOT NULL,
               notes jsonb NOT NULL DEFAULT '{}'::jsonb
           )"""
    )


def _insert(
    conn,
    *,
    ticker: str = "ZZUNIQ",
    signal_dt: str = "2099-09-17",
    strategy: str = "unit_strategy",
    recommendation_type: str = "experimental_defined_risk_option",
    status: str = "paper_candidate",
) -> int:
    return conn.execute(
        """INSERT INTO recommendations(ticker,recommendation_type,status,notes)
           VALUES (%s,%s,%s,jsonb_build_object(
               'signal_dt',%s::text,'strategy_name',%s::text))
           RETURNING id""",
        (ticker, recommendation_type, status, signal_dt, strategy),
    ).fetchone()[0]


def _drop_schema(conn, schema_name: str) -> None:
    conn.execute(
        sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
            sql.Identifier(schema_name)
        )
    )


def _index_names(conn) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            """SELECT indexname FROM pg_indexes
               WHERE schemaname=current_schema()
                 AND tablename='recommendations'"""
        ).fetchall()
    }


def test_migration_bootstraps_clean_schema_and_is_rerunnable():
    import psycopg

    schema_name = f"recommendation_unique_{uuid.uuid4().hex}"
    with psycopg.connect(resolve_test_dsn(), autocommit=True) as conn:
        try:
            _create_recommendations(conn, schema_name)
            conn.execute(_migration_sql())
            conn.execute(_migration_sql())

            assert {
                "uq_experimental_paper_recommendation_signal",
                "uq_paper_recommendation_signal",
            } <= _index_names(conn)
        finally:
            _drop_schema(conn, schema_name)


def test_migration_preserves_valid_rows_and_enforces_all_instrument_identity():
    import psycopg

    schema_name = f"recommendation_valid_{uuid.uuid4().hex}"
    with psycopg.connect(resolve_test_dsn(), autocommit=True) as conn:
        try:
            _create_recommendations(conn, schema_name)
            first_id = _insert(conn)
            _insert(
                conn,
                ticker="ZZOTHER",
                recommendation_type="equity_plus_option_spread_when_data_exists",
            )
            conn.execute(_migration_sql())

            assert conn.execute(
                "SELECT array_agg(id ORDER BY id),count(*) FROM recommendations"
            ).fetchone() == ([first_id, first_id + 1], 2)
            with pytest.raises(Exception):
                _insert(
                    conn,
                    recommendation_type="underlying_stock_fallback",
                )
        finally:
            _drop_schema(conn, schema_name)


def test_duplicate_preflight_reports_keys_and_aborts_without_cleanup():
    import psycopg

    schema_name = f"recommendation_duplicate_{uuid.uuid4().hex}"
    with psycopg.connect(resolve_test_dsn(), autocommit=True) as conn:
        try:
            _create_recommendations(conn, schema_name)
            ids = [_insert(conn), _insert(conn)]

            with pytest.raises(
                Exception,
                match=r"duplicate active recommendation identities.*ZZUNIQ.*2099-09-17.*unit_strategy",
            ):
                conn.execute(_migration_sql())
            conn.rollback()

            assert conn.execute(
                "SELECT array_agg(id ORDER BY id) FROM recommendations"
            ).fetchone()[0] == ids
            assert "uq_paper_recommendation_signal" not in _index_names(conn)
        finally:
            _drop_schema(conn, schema_name)


def test_migration_scopes_uniqueness_to_active_statuses_only():
    import psycopg

    schema_name = f"recommendation_status_{uuid.uuid4().hex}"
    with psycopg.connect(resolve_test_dsn(), autocommit=True) as conn:
        try:
            _create_recommendations(conn, schema_name)
            for status in ("watching", "rejected", "expired"):
                _insert(conn, status=status)
            _insert(conn, status="paper_candidate")
            conn.execute(_migration_sql())

            _insert(conn, status="rejected")
            with pytest.raises(Exception):
                _insert(
                    conn,
                    recommendation_type="underlying_stock_fallback",
                    status="paper_logged",
                )
            assert conn.execute(
                "SELECT count(*) FROM recommendations"
            ).fetchone() == (5,)
        finally:
            _drop_schema(conn, schema_name)


def test_concurrent_migration_attempts_serialize_and_succeed():
    import psycopg

    dsn = resolve_test_dsn()
    schema_name = f"recommendation_concurrent_{uuid.uuid4().hex}"
    errors: list[BaseException] = []
    with psycopg.connect(dsn, autocommit=True) as setup:
        _create_recommendations(setup, schema_name)
        _insert(setup)
        migrators = [psycopg.connect(dsn, autocommit=True) for _ in range(2)]
        try:
            for conn in migrators:
                conn.execute(
                    sql.SQL("SET search_path TO {}, public").format(
                        sql.Identifier(schema_name)
                    )
                )

            def migrate(conn) -> None:
                try:
                    conn.execute(_migration_sql())
                except BaseException as exc:  # asserted across thread boundary
                    errors.append(exc)

            threads = [threading.Thread(target=migrate, args=(conn,)) for conn in migrators]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
                assert not thread.is_alive()

            assert errors == []
            assert {
                "uq_experimental_paper_recommendation_signal",
                "uq_paper_recommendation_signal",
            } <= _index_names(setup)
        finally:
            for conn in migrators:
                conn.close()
            _drop_schema(setup, schema_name)


def test_migration_declares_active_status_contract():
    migration_sql = _migration_sql()
    for status in ACTIVE_STATUSES:
        assert status in migration_sql
