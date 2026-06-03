#!/usr/bin/env python3
"""Shared Wolfy database adapter with Postgres-first defaults.

Postgres is Wolfy's primary operational database. SQLite remains a legacy
compatibility store and must be selected through an explicit fallback flag so new
scripts do not quietly continue the old SQLite-first pattern.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
import os
import re
import sqlite3
from types import TracebackType
from typing import Literal
import warnings

import psycopg

DEFAULT_POSTGRES_DSN = "dbname=wolfy user=root host=/var/run/postgresql"
DEFAULT_SQLITE_PATH = Path("/root/.hermes/wolfy/wolfy.db")
TRUE_VALUES = {"1", "true", "t", "yes", "y", "on"}


class WolfyDatabaseError(RuntimeError):
    """Raised when the shared Wolfy DB adapter cannot connect safely."""


class WolfySQLiteFallbackWarning(RuntimeWarning):
    """Warns that a caller has fallen back to legacy SQLite compatibility."""


class DestructiveSQLError(WolfyDatabaseError):
    """Raised before known-destructive SQL is executed through the adapter."""


@dataclass(frozen=True)
class DatabaseConfig:
    """Connection convention for Wolfy operational code.

    backend is intentionally fixed to "postgres" by default. `allow_sqlite_fallback`
    is the explicit compatibility switch for legacy consumers during migration.
    """

    postgres_dsn: str = DEFAULT_POSTGRES_DSN
    sqlite_path: Path = DEFAULT_SQLITE_PATH
    backend: Literal["postgres"] = "postgres"
    allow_sqlite_fallback: bool = False


@dataclass(frozen=True)
class WolfyDBHandle(AbstractContextManager["WolfyDBHandle"]):
    """Context-manager wrapper exposing the selected backend and connection."""

    backend: Literal["postgres", "sqlite"]
    connection: object
    fallback_reason: str | None = None

    def __enter__(self) -> "WolfyDBHandle":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        close = getattr(self.connection, "close", None)
        if close is not None:
            close()
        return None


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in TRUE_VALUES


def get_database_config() -> DatabaseConfig:
    """Return Wolfy's Postgres-first DB config from environment.

    Preferred DSN env name is WOLFY_POSTGRES_DSN. WOLFY_PG_DSN remains accepted
    for existing scripts. SQLite fallback is off unless explicitly enabled with
    WOLFY_DB_ALLOW_SQLITE_FALLBACK=true/1/yes/on.
    """
    postgres_dsn = os.environ.get("WOLFY_POSTGRES_DSN") or os.environ.get("WOLFY_PG_DSN") or DEFAULT_POSTGRES_DSN
    sqlite_path = Path(os.environ.get("WOLFY_SQLITE_PATH", str(DEFAULT_SQLITE_PATH)))
    return DatabaseConfig(
        postgres_dsn=postgres_dsn,
        sqlite_path=sqlite_path,
        allow_sqlite_fallback=_env_truthy("WOLFY_DB_ALLOW_SQLITE_FALLBACK"),
    )


def connect_postgres(config: DatabaseConfig | None = None):
    """Connect to Wolfy's primary Postgres database."""
    cfg = config or get_database_config()
    return psycopg.connect(cfg.postgres_dsn)


def connect_sqlite_legacy(config: DatabaseConfig | None = None) -> sqlite3.Connection:
    """Connect to Wolfy's legacy SQLite compatibility database explicitly."""
    cfg = config or get_database_config()
    conn = sqlite3.connect(cfg.sqlite_path)
    conn.row_factory = sqlite3.Row
    return conn


def connect_wolfy_db(config: DatabaseConfig | None = None) -> WolfyDBHandle:
    """Connect to Postgres by default, with opt-in legacy SQLite fallback only.

    The fallback path is intentionally noisy: it raises unless enabled and emits a
    RuntimeWarning when used, so cron/report code can surface stale migration
    paths instead of silently writing to SQLite.
    """
    cfg = config or get_database_config()
    try:
        return WolfyDBHandle(backend="postgres", connection=connect_postgres(cfg))
    except Exception as exc:  # noqa: BLE001 - adapter boundary records any driver failure
        if not cfg.allow_sqlite_fallback:
            raise WolfyDatabaseError(
                "Postgres connection failed and SQLite fallback is disabled; "
                "set WOLFY_DB_ALLOW_SQLITE_FALLBACK=true only for explicit legacy compatibility."
            ) from exc
        warnings.warn(
            f"Using legacy fallback SQLite database at {cfg.sqlite_path}; Postgres error: {exc}",
            WolfySQLiteFallbackWarning,
            stacklevel=2,
        )
        return WolfyDBHandle(
            backend="sqlite",
            connection=connect_sqlite_legacy(cfg),
            fallback_reason=str(exc),
        )


_DESTRUCTIVE_PATTERNS = [
    re.compile(r"\bdrop\s+(table|database|schema|index|view|materialized\s+view)\b", re.IGNORECASE),
    re.compile(r"\btruncate\s+table\b", re.IGNORECASE),
    re.compile(r"\bdelete\s+from\b", re.IGNORECASE),
    re.compile(r"\balter\s+table\b.*\bdrop\s+(column|constraint)\b", re.IGNORECASE | re.DOTALL),
]


def assert_non_destructive_sql(sql: str) -> None:
    """Reject SQL statements that violate Wolfy's no-destructive-migration guardrail.

    This is a safety net for shared adapter users, not a full SQL parser. It
    catches the high-risk operations that should never be part of routine Wolfy
    Postgres-primary migration work without explicit human approval.
    """
    compact_sql = " ".join(sql.strip().split())
    for pattern in _DESTRUCTIVE_PATTERNS:
        if pattern.search(compact_sql):
            raise DestructiveSQLError(f"Destructive SQL is not allowed by Wolfy guardrails: {compact_sql}")


def execute_guarded(conn, sql: str, params: tuple[object, ...] | None = None):
    """Execute SQL after applying the destructive-operation guard."""
    assert_non_destructive_sql(sql)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur
