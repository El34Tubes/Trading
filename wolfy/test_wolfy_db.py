#!/usr/bin/env python3
"""Tests for Wolfy's shared Postgres-first DB adapter."""
from __future__ import annotations

import sqlite3

import pytest

import wolfy_db


def test_default_config_is_postgres_first_and_fallback_is_opt_in(monkeypatch):
    monkeypatch.delenv("WOLFY_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("WOLFY_PG_DSN", raising=False)
    monkeypatch.delenv("WOLFY_DB_ALLOW_SQLITE_FALLBACK", raising=False)

    config = wolfy_db.get_database_config()

    assert config.backend == "postgres"
    assert config.postgres_dsn == "dbname=wolfy user=root host=/var/run/postgresql"
    assert str(config.sqlite_path) == "/root/.hermes/wolfy/wolfy.db"
    assert config.allow_sqlite_fallback is False


def test_postgres_dsn_prefers_new_name_but_accepts_legacy_name(monkeypatch):
    monkeypatch.setenv("WOLFY_PG_DSN", "dbname=legacy")
    monkeypatch.delenv("WOLFY_POSTGRES_DSN", raising=False)
    assert wolfy_db.get_database_config().postgres_dsn == "dbname=legacy"

    monkeypatch.setenv("WOLFY_POSTGRES_DSN", "dbname=new")
    assert wolfy_db.get_database_config().postgres_dsn == "dbname=new"


def test_connect_wolfy_db_connects_to_live_postgres_by_default():
    with wolfy_db.connect_wolfy_db() as handle:
        assert handle.backend == "postgres"
        with handle.connection.cursor() as cur:
            cur.execute("select current_database(), to_regclass('public.agent_runs') is not null")
            database_name, has_agent_runs = cur.fetchone()

    assert database_name == "wolfy"
    assert has_agent_runs is True


def test_sqlite_fallback_requires_explicit_opt_in_and_emits_warning(monkeypatch, tmp_path):
    sqlite_path = tmp_path / "legacy.db"
    sqlite3.connect(sqlite_path).execute("create table smoke(id integer)").connection.close()

    def fail_postgres_connect(*_args, **_kwargs):
        raise RuntimeError("postgres unavailable")

    monkeypatch.setattr(wolfy_db.psycopg, "connect", fail_postgres_connect)

    config_without_fallback = wolfy_db.DatabaseConfig(
        postgres_dsn="dbname=missing",
        sqlite_path=sqlite_path,
        allow_sqlite_fallback=False,
    )
    with pytest.raises(wolfy_db.WolfyDatabaseError, match="SQLite fallback is disabled"):
        wolfy_db.connect_wolfy_db(config_without_fallback)

    config_with_fallback = wolfy_db.DatabaseConfig(
        postgres_dsn="dbname=missing",
        sqlite_path=sqlite_path,
        allow_sqlite_fallback=True,
    )
    with pytest.warns(wolfy_db.WolfySQLiteFallbackWarning, match="legacy fallback"):
        with wolfy_db.connect_wolfy_db(config_with_fallback) as handle:
            assert handle.backend == "sqlite"
            assert handle.connection.execute("select name from sqlite_master where type='table'").fetchone()[0] == "smoke"


def test_agent_coordination_uses_shared_postgres_adapter(monkeypatch):
    import wolfy_agent_coordination

    calls = []

    def fake_connect_postgres(config):
        calls.append(config.postgres_dsn)
        return "postgres-connection"

    monkeypatch.setattr(wolfy_agent_coordination, "connect_postgres", fake_connect_postgres)

    assert wolfy_agent_coordination.DEFAULT_PG_DSN == wolfy_db.DEFAULT_POSTGRES_DSN
    assert wolfy_agent_coordination.connect("dbname=shared-adapter-test") == "postgres-connection"
    assert calls == ["dbname=shared-adapter-test"]


def test_guard_rejects_destructive_sql_before_execution():
    safe_statements = [
        "select count(*) from agent_runs",
        "create index if not exists idx_agent_runs_status_test on agent_runs(status)",
        "insert into agent_runs(agent_name, role, status) values (%s, %s, %s)",
        "update agent_runs set status=%s where id=%s",
    ]
    for statement in safe_statements:
        wolfy_db.assert_non_destructive_sql(statement)

    destructive_statements = [
        "drop table agent_runs",
        "truncate table knowledge_chunks",
        "delete from agent_tasks",
        "alter table knowledge_chunks drop column embedding",
        "drop database wolfy",
    ]
    for statement in destructive_statements:
        with pytest.raises(wolfy_db.DestructiveSQLError):
            wolfy_db.assert_non_destructive_sql(statement)
