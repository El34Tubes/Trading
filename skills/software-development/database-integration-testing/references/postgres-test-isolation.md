# PostgreSQL Test Isolation Recipe

## Pre-collection environment redirection

Use this when tested modules compute constants such as `DEFAULT_DSN = os.environ.get(...)` during import.

```python
# conftest.py
from __future__ import annotations

import os
import pytest
from psycopg.conninfo import conninfo_to_dict

_MISSING = object()
_original = _MISSING
_test_dsn = None


def pytest_configure(config):
    del config
    global _original, _test_dsn
    _original = os.environ.get("APP_POSTGRES_DSN", _MISSING)
    _test_dsn = provision_test_database()
    assert conninfo_to_dict(_test_dsn)["dbname"] == "app_test"
    os.environ["APP_POSTGRES_DSN"] = _test_dsn


def pytest_unconfigure(config):
    del config
    if _original is _MISSING:
        os.environ.pop("APP_POSTGRES_DSN", None)
    else:
        os.environ["APP_POSTGRES_DSN"] = str(_original)


@pytest.fixture(scope="session", autouse=True)
def isolate_implicit_writes():
    assert conninfo_to_dict(_test_dsn)["dbname"] == "app_test"
    os.environ["APP_POSTGRES_DSN"] = _test_dsn
    yield
```

`pytest_configure` is the important pre-collection hook. The autouse fixture is a second guard, not a substitute.

## Dedicated connection helper

A safe helper should:

- parse the DSN with the driver rather than regex;
- accept exactly the dedicated database name;
- check `current_database()` after connecting;
- rollback in `finally` for test-owned connections;
- serialize schema bootstrap with an advisory lock if needed.

```python
@contextmanager
def test_connection():
    conn = psycopg.connect(provision_test_database())
    try:
        assert conn.execute("select current_database()").fetchone()[0] == "app_test"
        yield conn
    finally:
        conn.rollback()
        conn.close()
```

Rollback does not cover an application helper that opens and commits a separate connection. The pre-collection DSN redirect is what protects those calls.

## Side-effect-safe regression ordering

```python
def test_implicit_real_write_is_redirected(tmp_path):
    implicit_dsn = os.environ.get("APP_POSTGRES_DSN")
    assert implicit_dsn is not None
    assert conninfo_to_dict(implicit_dsn)["dbname"] == "app_test"

    production_before = read_only_production_count()
    result = real_application_write(tmp_path / "compat.db", complete_fixture())

    assert row_exists_in_test_database(result.id)
    assert read_only_production_count() == production_before
```

The first RED run stops at the identity assertion, before the real write helper executes.

## Verification commands

Adapt paths and DSNs to the repository:

```bash
python -m pytest -q path/to/regression_test.py::test_implicit_real_write_is_redirected
python -m pytest -q path/to/focused_db_tests.py
python -m pytest -q relevant/test/subtree

psql -X "$TEST_DSN" -v ON_ERROR_STOP=1 -f schema.sql
psql -X "$TEST_DSN" -v ON_ERROR_STOP=1 -f schema.sql

ruff check <changed-python-files>
python -m py_compile <changed-python-files>
git diff --check
```

Capture and compare exact production values separately before and after the suite. Avoid fuzzy statements such as “counts look unchanged.”

## Static audit categories

For each test match involving `connect`, `persist`, `save`, `insert`, `log`, or the primary DSN variable, record whether it is:

1. a real implicit write protected by pre-collection redirection;
2. a real explicit test-DSN write;
3. a mocked write;
4. a negative configuration test that temporarily overrides/deletes environment state;
5. a read-only production baseline probe.

Any other explicit production connection is a blocker until explained or migrated.