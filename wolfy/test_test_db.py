from __future__ import annotations

import os

import pytest

PRODUCTION_DSN = "dbname=wolfy user=root host=/var/run/postgresql"
APPROVED_STRATEGY = "liquid_rs_breakout_close_confirm_1r"


def _production_immutable_snapshot():
    """Read the complete production guard set in a forced read-only session."""
    import psycopg
    from psycopg import sql

    with psycopg.connect(
        PRODUCTION_DSN,
        options="-c default_transaction_read_only=on",
    ) as production:
        assert production.execute("SHOW transaction_read_only").fetchone()[0] == "on"
        assert production.execute("SELECT current_database()").fetchone()[0] == "wolfy"
        counts = {}
        for table in ("strategies", "signals", "recommendations", "paper_trades"):
            query = sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
            counts[table] = production.execute(query).fetchone()[0]
        counts["approved_strategies"] = production.execute(
            "SELECT count(*) FROM strategies WHERE status='approved'"
        ).fetchone()[0]
        strategy = production.execute(
            """
            SELECT status,
                   latest_oos_verdict,
                   metadata,
                   metadata->>'approval_scope' AS approval_scope,
                   metadata->>'paper_recommendation_approval'
                     AS paper_recommendation_approval,
                   metadata->>'approval_required_for_recommendations'
                     AS approval_required_for_recommendations
            FROM strategies
            WHERE name=%s
            """,
            (APPROVED_STRATEGY,),
        ).fetchone()
        assert strategy is not None
        return {"counts": counts, "approved_strategy": strategy}


def test_test_dsn_rejects_live_wolfy_database(monkeypatch):
    from test_db import resolve_test_dsn

    monkeypatch.setenv(
        "WOLFY_TEST_POSTGRES_DSN",
        "dbname=wolfy user=root host=/var/run/postgresql",
    )

    with pytest.raises(ValueError, match="dedicated test database"):
        resolve_test_dsn()


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://root@localhost/wolfy",
        "dbname=wolfy_prod user=root host=/var/run/postgresql",
        "postgresql://root@localhost/wolfy-production",
    ],
)
def test_test_dsn_rejects_production_like_database_names(monkeypatch, dsn):
    from test_db import resolve_test_dsn

    monkeypatch.setenv("WOLFY_TEST_POSTGRES_DSN", dsn)

    with pytest.raises(ValueError, match="dedicated test database"):
        resolve_test_dsn()


@pytest.mark.parametrize(
    "dsn",
    [
        "host=production-db.internal dbname=wolfy_test user=prod_admin password=dummy",
        "host=database.example.com dbname=wolfy_test user=root",
        "host=10.20.30.40 dbname=wolfy_test user=root",
        "host=localhost dbname=wolfy_test user=root password=dummy",
        "service=wolfy_prod dbname=wolfy_test user=root",
        "host=/var/run/postgresql dbname=wolfy_test user=prod_admin",
        "postgresql://prod_admin:dummy@production-db.internal/wolfy_test",
        "postgresql://root@10.20.30.40/wolfy_test?sslmode=require",
        "postgresql://root@localhost/wolfy_test",
    ],
)
def test_test_dsn_rejects_unsafe_endpoint_credentials_and_users(monkeypatch, dsn):
    from test_db import resolve_test_dsn

    monkeypatch.setenv("WOLFY_TEST_POSTGRES_DSN", dsn)

    with pytest.raises(ValueError, match="local peer-auth"):
        resolve_test_dsn()


def test_test_dsn_accepts_explicit_local_peer_auth_root(monkeypatch):
    from test_db import resolve_test_dsn

    dsn = "host=/var/run/postgresql dbname=wolfy_test user=root"
    monkeypatch.setenv("WOLFY_TEST_POSTGRES_DSN", dsn)

    assert resolve_test_dsn() == dsn


def test_admin_dsn_refuses_unsafe_remote_target():
    from test_db import _admin_dsn

    with pytest.raises(ValueError, match="local peer-auth"):
        _admin_dsn(
            "host=production-db.internal dbname=wolfy_test "
            "user=prod_admin password=dummy"
        )


def test_fixture_identity_is_unique_future_dated_and_namespaced():
    from test_db import future_fixture

    first = future_fixture("signals")
    second = future_fixture("signals")

    assert first != second
    assert first.ticker.startswith("ZZSIGNALS")
    assert first.strategy_name.startswith("unit_signals_")
    assert first.signal_dt.year >= 2100


def test_provisioning_is_idempotent_and_test_connection_rolls_back():
    import psycopg

    from test_db import (
        future_fixture,
        provision_test_database,
        resolve_test_dsn,
        test_connection,
    )

    provision_test_database()
    provision_test_database()

    fixture = future_fixture("rollback")
    with test_connection() as conn:
        assert conn.execute("SELECT current_database()").fetchone()[0] == "wolfy_test"
        conn.execute(
            "INSERT INTO strategies(name, setup_type, status) VALUES (%s, 'unit', 'research_only')",
            (fixture.strategy_name,),
        )
        assert conn.execute(
            "SELECT count(*) FROM strategies WHERE name=%s", (fixture.strategy_name,)
        ).fetchone()[0] == 1

    with psycopg.connect(resolve_test_dsn()) as verification_conn:
        assert verification_conn.execute(
            "SELECT count(*) FROM strategies WHERE name=%s", (fixture.strategy_name,)
        ).fetchone()[0] == 0
        assert verification_conn.execute(
            "SELECT to_regclass('public.option_structure_evaluations') IS NOT NULL"
        ).fetchone()[0] is True


def test_pytest_session_redirects_implicit_recommendation_writes_from_production(
    tmp_path,
):
    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    from recommendation_logger import log_recommendation
    from test_db import future_fixture
    from test_postgres_primary_pipeline import _complete_idea

    implicit_dsn = os.environ.get("WOLFY_POSTGRES_DSN")
    assert implicit_dsn is not None
    assert conninfo_to_dict(implicit_dsn).get("dbname") == "wolfy_test"

    production_before = _production_immutable_snapshot()
    approved = production_before["approved_strategy"]
    assert approved[0] == "approved"
    assert approved[1] is True
    assert approved[3:] == ("paper_only_no_live_execution", "true", "true")
    fixture = future_fixture("implicitrec")
    try:
        result = log_recommendation(tmp_path / "compat.db", _complete_idea(fixture))

        assert result["postgres_primary"] is True
        with psycopg.connect(implicit_dsn) as test_db:
            assert test_db.execute(
                "SELECT count(*) FROM recommendations WHERE id=%s",
                (result["postgres_recommendation_id"],),
            ).fetchone()[0] == 1
        production_after = _production_immutable_snapshot()
    finally:
        with psycopg.connect(implicit_dsn) as test_db:
            assert test_db.execute("SELECT current_database()").fetchone()[0] == (
                "wolfy_test"
            )
            test_db.execute(
                "DELETE FROM recommendations WHERE ticker=%s AND thesis=%s",
                (
                    fixture.ticker,
                    "Postgres-primary smoke idea; deterministic test data only.",
                ),
            )
            test_db.commit()

    assert production_after == production_before
    with psycopg.connect(implicit_dsn) as test_db:
        assert test_db.execute(
            "SELECT count(*) FROM recommendations WHERE ticker=%s",
            (fixture.ticker,),
        ).fetchone()[0] == 0
