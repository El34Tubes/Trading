#!/usr/bin/env python3
"""Shared Wolfy database adapter for Wolfy's Postgres-only operational database.

SQLite has been retired from Wolfy. New/live scripts must connect to Postgres
and fail clearly if Postgres is unavailable.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
import os
import re
from types import TracebackType
from typing import Literal

import psycopg

DEFAULT_POSTGRES_DSN = "dbname=wolfy user=root host=/var/run/postgresql"


class WolfyDatabaseError(RuntimeError):
    """Raised when the shared Wolfy DB adapter cannot connect safely."""


class DestructiveSQLError(WolfyDatabaseError):
    """Raised before known-destructive SQL is executed through the adapter."""


@dataclass(frozen=True)
class DatabaseConfig:
    """Connection convention for Wolfy operational code."""

    postgres_dsn: str = DEFAULT_POSTGRES_DSN
    backend: Literal["postgres"] = "postgres"


@dataclass(frozen=True)
class WolfyDBHandle(AbstractContextManager["WolfyDBHandle"]):
    """Context-manager wrapper exposing the selected Postgres connection."""

    backend: Literal["postgres"]
    connection: object

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


def get_database_config() -> DatabaseConfig:
    """Return Wolfy's Postgres-only DB config from environment."""
    postgres_dsn = os.environ.get("WOLFY_POSTGRES_DSN") or os.environ.get("WOLFY_PG_DSN") or DEFAULT_POSTGRES_DSN
    return DatabaseConfig(postgres_dsn=postgres_dsn)


def connect_postgres(config: DatabaseConfig | None = None):
    """Connect to Wolfy's primary Postgres database."""
    cfg = config or get_database_config()
    return psycopg.connect(cfg.postgres_dsn)


def connect_wolfy_db(config: DatabaseConfig | None = None) -> WolfyDBHandle:
    """Connect to Wolfy's Postgres operational database.

    SQLite fallback has been removed. Any failure here is a live Postgres
    availability/configuration problem, not an invitation to use a local file DB.
    """
    cfg = config or get_database_config()
    try:
        return WolfyDBHandle(backend="postgres", connection=connect_postgres(cfg))
    except Exception as exc:  # noqa: BLE001 - adapter boundary records any driver failure
        raise WolfyDatabaseError("Postgres connection failed; Wolfy SQLite fallback has been retired.") from exc


_DESTRUCTIVE_PATTERNS = [
    re.compile(r"\bdrop\s+(table|database|schema|index|view|materialized\s+view)\b", re.IGNORECASE),
    re.compile(r"\btruncate\s+table\b", re.IGNORECASE),
    re.compile(r"\bdelete\s+from\b", re.IGNORECASE),
    re.compile(r"\balter\s+table\b.*\bdrop\s+(column|constraint)\b", re.IGNORECASE | re.DOTALL),
]


def assert_non_destructive_sql(sql: str) -> None:
    """Reject SQL statements that violate Wolfy's no-destructive-migration guardrail."""
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
