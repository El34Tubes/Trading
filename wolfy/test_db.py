from __future__ import annotations

import os
import re
import subprocess
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator

TEST_DATABASE_NAME = "wolfy_test"
DEFAULT_TEST_POSTGRES_DSN = (
    f"dbname={TEST_DATABASE_NAME} user=root host=/var/run/postgresql"
)


def resolve_test_dsn() -> str:
    """Return a DSN that is guaranteed to target Wolfy's dedicated test DB."""
    from psycopg.conninfo import conninfo_to_dict

    dsn = os.environ.get("WOLFY_TEST_POSTGRES_DSN", DEFAULT_TEST_POSTGRES_DSN)
    database = conninfo_to_dict(dsn).get("dbname")
    if database != TEST_DATABASE_NAME:
        raise ValueError(
            f"WOLFY_TEST_POSTGRES_DSN must target the dedicated test database "
            f"{TEST_DATABASE_NAME!r}; got {database!r}"
        )
    return dsn


@dataclass(frozen=True)
class FutureFixture:
    ticker: str
    strategy_name: str
    signal_dt: date


def future_fixture(namespace: str = "fixture") -> FutureFixture:
    """Return collision-resistant names and a date outside production history."""
    slug = re.sub(r"[^a-z0-9]+", "", namespace.lower())[:12] or "fixture"
    token = uuid.uuid4().hex[:10]
    day_offset = int(token, 16) % 30_000
    return FutureFixture(
        ticker=f"ZZ{slug.upper()}{token[:6].upper()}",
        strategy_name=f"unit_{slug}_{token}",
        signal_dt=date(2100, 1, 1) + timedelta(days=day_offset),
    )


def _admin_dsn(test_dsn: str) -> str:
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    params = conninfo_to_dict(test_dsn)
    params["dbname"] = "postgres"
    return make_conninfo(**params)


def _apply_schema(dsn: str) -> None:
    import psycopg

    base = Path(__file__).resolve().parent
    with psycopg.connect(dsn, autocommit=True) as conn:
        if conn.execute("SELECT current_database()").fetchone()[0] != TEST_DATABASE_NAME:
            raise RuntimeError("refusing to apply test schema outside wolfy_test")
        conn.execute("SELECT pg_advisory_lock(hashtext('wolfy_test_schema'))")
        try:
            # Bootstrap dependencies before applying the repository-wide schema.
            conn.execute(
                (base / "migrations/20260601_eod_section6_schema.sql").read_text()
            )
            from eod_price_features import ensure_eod_feature_schema
            from wolfy_postgres_pipeline import ensure_operational_tables

            ensure_eod_feature_schema(conn)
            ensure_operational_tables(conn)
            conn.execute((base / "postgres_init.sql").read_text())

            from eod_backtest import ensure_backtest_schema
            from eod_monitoring import ensure_monitoring_schema
            from eod_signals import ensure_signal_schema
            from recommendation_outcome_review import ensure_paper_trade_metric_columns

            ensure_signal_schema(conn)
            ensure_backtest_schema(conn)
            ensure_monitoring_schema(conn)
            ensure_paper_trade_metric_columns(conn)
            for migration in (
                "20260812_free_market_structure_volatility.sql",
                "20260812_option_structure_evaluations.sql",
            ):
                conn.execute((base / "migrations" / migration).read_text())
        finally:
            conn.execute("SELECT pg_advisory_unlock(hashtext('wolfy_test_schema'))")


def _create_database_with_local_peer_auth(dsn: str) -> None:
    from psycopg.conninfo import conninfo_to_dict

    params = conninfo_to_dict(dsn)
    if (
        os.geteuid() != 0
        or params.get("host") != "/var/run/postgresql"
        or params.get("password")
    ):
        raise PermissionError(
            "creating wolfy_test requires CREATEDB or local root peer-auth access"
        )
    subprocess.run(
        [
            "runuser",
            "-u",
            "postgres",
            "--",
            "createdb",
            "--host=/var/run/postgresql",
            "--username=postgres",
            "--owner=root",
            TEST_DATABASE_NAME,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _ensure_local_extensions(dsn: str) -> None:
    from psycopg.conninfo import conninfo_to_dict

    params = conninfo_to_dict(dsn)
    if (
        os.geteuid() != 0
        or params.get("host") != "/var/run/postgresql"
        or params.get("password")
    ):
        return
    subprocess.run(
        [
            "runuser",
            "-u",
            "postgres",
            "--",
            "psql",
            "-X",
            "--host=/var/run/postgresql",
            "--username=postgres",
            f"--dbname={TEST_DATABASE_NAME}",
            "--set=ON_ERROR_STOP=1",
            "--command=CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def provision_test_database() -> str:
    """Create only ``wolfy_test`` when absent and idempotently apply its schema."""
    import psycopg
    from psycopg import sql
    from psycopg.errors import DuplicateDatabase, InsufficientPrivilege

    dsn = resolve_test_dsn()
    with psycopg.connect(_admin_dsn(dsn), autocommit=True) as admin:
        exists = admin.execute(
            "SELECT 1 FROM pg_database WHERE datname=%s", (TEST_DATABASE_NAME,)
        ).fetchone()
        if not exists:
            try:
                admin.execute(
                    sql.SQL("CREATE DATABASE {}").format(
                        sql.Identifier(TEST_DATABASE_NAME)
                    )
                )
            except DuplicateDatabase:
                pass
            except InsufficientPrivilege:
                _create_database_with_local_peer_auth(dsn)
    _ensure_local_extensions(dsn)
    _apply_schema(dsn)
    return dsn


@contextmanager
def test_connection() -> Iterator[object]:
    """Yield an isolated Postgres connection and always roll its work back."""
    import psycopg

    conn = psycopg.connect(provision_test_database())
    try:
        database = conn.execute("SELECT current_database()").fetchone()[0]
        if database != TEST_DATABASE_NAME:
            raise RuntimeError("refusing to run a test transaction outside wolfy_test")
        yield conn
    finally:
        conn.rollback()
        conn.close()


# Prevent pytest from collecting the imported context manager as a test.
test_connection.__test__ = False
