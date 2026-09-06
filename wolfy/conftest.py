from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Callable, Generator
from pathlib import Path
from types import ModuleType

import pytest
from psycopg.conninfo import conninfo_to_dict

_WORKTREE_WOLFY = Path(__file__).resolve().parent
_PRODUCTION_WOLFY = Path("/root/.hermes/wolfy").resolve()
_REQUIRED_LOCAL_MODULES = (
    "orchestration_runner",
    "eod_readiness",
    "eod_price_features",
    "eod_backtest",
    "eod_monitoring",
    "eod_signals",
    "recommendation_outcome_review",
)
_DEFAULT_DSN_MODULES = _REQUIRED_LOCAL_MODULES[2:]
_LOCAL_MODULE_NAMES = frozenset(path.stem for path in _WORKTREE_WOLFY.glob("*.py"))


def _resolved_path(value: str) -> Path:
    return Path(value or os.curdir).resolve()


def _module_origin(module: ModuleType) -> Path | None:
    origin = getattr(module, "__file__", None)
    return Path(origin).resolve() if origin else None


def _restore_worktree_imports(*, import_required: bool) -> None:
    """Make this checkout authoritative and discard cached foreign Wolfy modules."""
    sys.path[:] = [
        entry
        for entry in sys.path
        if _resolved_path(entry) not in {_WORKTREE_WOLFY, _PRODUCTION_WOLFY}
    ]
    sys.path.insert(0, str(_WORKTREE_WOLFY))
    importlib.invalidate_caches()

    for module_name, module in tuple(sys.modules.items()):
        if "." in module_name or module_name not in _LOCAL_MODULE_NAMES:
            continue
        origin = _module_origin(module)
        if origin is None or origin.is_relative_to(_WORKTREE_WOLFY):
            continue
        if origin.is_relative_to(_PRODUCTION_WOLFY):
            sys.modules.pop(module_name, None)
            continue
        raise pytest.UsageError(
            f"refusing non-worktree {module_name} import from {origin}"
        )

    if not import_required:
        return

    for module_name in _REQUIRED_LOCAL_MODULES:
        module = importlib.import_module(module_name)
        origin = _module_origin(module)
        if origin is None or not origin.is_relative_to(_WORKTREE_WOLFY):
            raise pytest.UsageError(
                f"{module_name} must resolve under {_WORKTREE_WOLFY}, got {origin}"
            )


# conftest imports test_db by its flat module name, so establish the worktree path
# before that import as well as at pytest lifecycle boundaries.
_restore_worktree_imports(import_required=False)

from test_db import TEST_DATABASE_NAME, provision_test_database, resolve_test_dsn  # noqa: E402

_MISSING = object()
_original_postgres_dsn: str | object = _MISSING
_test_dsn: str | None = None


def _restore_isolated_session_state() -> None:
    assert _test_dsn is not None
    assert conninfo_to_dict(_test_dsn).get("dbname") == TEST_DATABASE_NAME
    os.environ["WOLFY_POSTGRES_DSN"] = _test_dsn
    _restore_worktree_imports(import_required=True)
    for module_name in _DEFAULT_DSN_MODULES:
        module = sys.modules[module_name]
        if conninfo_to_dict(module.DEFAULT_DSN).get("dbname") != TEST_DATABASE_NAME:
            raise pytest.UsageError(
                f"{module_name}.DEFAULT_DSN escaped isolated database {TEST_DATABASE_NAME}"
            )


def pytest_configure(config):
    """Redirect imports and default Postgres connections before test imports."""
    del config
    global _original_postgres_dsn, _test_dsn
    _restore_worktree_imports(import_required=False)
    _original_postgres_dsn = os.environ.get("WOLFY_POSTGRES_DSN", _MISSING)
    _test_dsn = resolve_test_dsn()
    os.environ["WOLFY_POSTGRES_DSN"] = _test_dsn
    try:
        provision_test_database()
        _restore_isolated_session_state()
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
def isolate_implicit_postgres_writes() -> Generator[None, None, None]:
    """Guard every implicit/default Postgres write behind ``wolfy_test``."""
    assert _test_dsn is not None
    assert conninfo_to_dict(_test_dsn).get("dbname") == TEST_DATABASE_NAME
    os.environ["WOLFY_POSTGRES_DSN"] = _test_dsn
    yield


@pytest.fixture(autouse=True)
def restore_worktree_imports() -> Generator[Callable[[], None], None, None]:
    """Repair path/module pollution before and after every test."""

    def restore() -> None:
        _restore_isolated_session_state()

    restore()
    yield restore
    restore()
