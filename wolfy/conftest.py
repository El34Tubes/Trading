from __future__ import annotations

import os

import pytest
from psycopg.conninfo import conninfo_to_dict

from test_db import TEST_DATABASE_NAME, provision_test_database, resolve_test_dsn

_MISSING = object()
_original_postgres_dsn: str | object = _MISSING
_test_dsn: str | None = None


def pytest_configure(config):
    """Redirect default Postgres connections before pytest imports schema modules."""
    del config
    global _original_postgres_dsn, _test_dsn
    _original_postgres_dsn = os.environ.get("WOLFY_POSTGRES_DSN", _MISSING)
    _test_dsn = resolve_test_dsn()
    os.environ["WOLFY_POSTGRES_DSN"] = _test_dsn
    try:
        provision_test_database()
    except BaseException:
        if _original_postgres_dsn is _MISSING:
            os.environ.pop("WOLFY_POSTGRES_DSN", None)
        else:
            os.environ["WOLFY_POSTGRES_DSN"] = str(_original_postgres_dsn)
        raise


def pytest_unconfigure(config):
    """Restore the caller's Postgres environment after the test session."""
    del config
    if _original_postgres_dsn is _MISSING:
        os.environ.pop("WOLFY_POSTGRES_DSN", None)
    else:
        os.environ["WOLFY_POSTGRES_DSN"] = str(_original_postgres_dsn)


@pytest.fixture(scope="session", autouse=True)
def isolate_implicit_postgres_writes():
    """Guard every implicit/default Postgres write behind ``wolfy_test``."""
    assert _test_dsn is not None
    assert conninfo_to_dict(_test_dsn).get("dbname") == TEST_DATABASE_NAME
    os.environ["WOLFY_POSTGRES_DSN"] = _test_dsn
    yield
