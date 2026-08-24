from __future__ import annotations

import os

import pytest


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
    from test_postgres_primary_pipeline import _complete_idea

    implicit_dsn = os.environ.get("WOLFY_POSTGRES_DSN")
    assert implicit_dsn is not None
    assert conninfo_to_dict(implicit_dsn).get("dbname") == "wolfy_test"

    production_dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    with psycopg.connect(production_dsn) as production:
        production_before = production.execute(
            "SELECT count(*) FROM recommendations"
        ).fetchone()[0]

    result = log_recommendation(tmp_path / "compat.db", _complete_idea())

    assert result["postgres_primary"] is True
    with psycopg.connect(implicit_dsn) as test_db:
        assert test_db.execute(
            "SELECT count(*) FROM recommendations WHERE id=%s",
            (result["postgres_recommendation_id"],),
        ).fetchone()[0] == 1
    with psycopg.connect(production_dsn) as production:
        assert production.execute(
            "SELECT count(*) FROM recommendations"
        ).fetchone()[0] == production_before
