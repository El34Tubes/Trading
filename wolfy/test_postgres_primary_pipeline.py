#!/usr/bin/env python3
"""Smoke tests for Wolfy's Postgres-primary operational pipeline helpers."""
from __future__ import annotations

import json

import pytest

import wolfy_postgres_pipeline as pgpipe
from recommendation_logger import log_recommendation
from wolfy_scanner import persist_scan


def _sample_ranked():
    return [
        (
            12.5,
            "MSFT",
            {
                "date": "2026-06-03",
                "close": 425.0,
                "r5": 1.0,
                "r20": 4.2,
                "r60": 8.1,
                "vs20": 2.0,
                "vs50": 6.0,
                "atr": 7.5,
                "avgvol": 30_000_000,
                "hi20": 430.0,
                "lo20": 400.0,
                "extension_penalty": 0,
                "liquidity_pass": 1,
                "rank_reasons": "pytest smoke",
            },
        )
    ]


def _complete_idea():
    return {
        "ticker": "MSFT",
        "action": "buy",
        "instrument_type": "equity",
        "robinhood_assumption": "Robinhood-listed U.S. large-cap common stock",
        "thesis": "Postgres-primary smoke idea; deterministic test data only.",
        "setup": "Test pullback setup.",
        "entry_trigger": "Buy only above 425.",
        "stop_invalidation": "Close below 410 invalidates.",
        "target_exit": "Trim near 455.",
        "risk_reward": "2R",
        "confidence": "medium",
        "size_guidance": "Risk <=0.75% of $5k paper account.",
        "holding_period": "2-6 weeks",
        "risk_notes": "pytest smoke only; no real trade.",
        "jonah_refs": ["pytest:postgres-primary"],
    }


def test_postgres_operational_schema_has_scanner_recommendation_and_ledger_tables():
    with pgpipe.connect_postgres() as conn:
        pgpipe.ensure_operational_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                select table_name
                from information_schema.tables
                where table_schema='public'
                  and table_name in ('scanner_runs','scanner_results','recommendations','paper_trades','recommendation_outcomes')
                order by table_name
                """
            )
            assert [row[0] for row in cur.fetchall()] == [
                "paper_trades",
                "recommendation_outcomes",
                "recommendations",
                "scanner_results",
                "scanner_runs",
            ]


def test_scanner_persist_dual_writes_postgres_first_and_keeps_sqlite_compatibility(tmp_path):
    sqlite_db = tmp_path / "wolfy.db"
    with pgpipe.connect_postgres() as conn:
        before = pgpipe.count_rows(conn, "scanner_runs")

    sqlite_run_id = persist_scan(_sample_ranked(), sqlite_db, "ticker-list", notes="pytest-postgres-primary")

    assert sqlite_run_id == 1
    with pgpipe.connect_postgres() as conn:
        after = pgpipe.count_rows(conn, "scanner_runs")
        assert after == before + 1
        with conn.cursor() as cur:
            cur.execute("select id from scanner_runs where notes=%s order by id desc limit 1", ("pytest-postgres-primary",))
            pg_run_id = cur.fetchone()[0]
            cur.execute("select ticker, score, data_date from scanner_results where run_id=%s", (pg_run_id,))
            assert cur.fetchone() == ("MSFT", pytest.approx(12.5), __import__('datetime').date(2026, 6, 3))


def test_recommendation_logger_dual_writes_postgres_and_returns_fallback_free_metadata(tmp_path):
    sqlite_db = tmp_path / "wolfy.db"
    with pgpipe.connect_postgres() as conn:
        before = pgpipe.count_rows(conn, "recommendations")

    result = log_recommendation(sqlite_db, _complete_idea())

    assert result["status"] == "pending_review"
    assert result["postgres_primary"] is True
    assert result["sqlite_compatibility"] is True
    with pgpipe.connect_postgres() as conn:
        assert pgpipe.count_rows(conn, "recommendations") == before + 1
        with conn.cursor() as cur:
            cur.execute("select ticker, status, notes->>'validator' from recommendations where id=%s", (result["postgres_recommendation_id"],))
            assert cur.fetchone() == ("MSFT", "pending_review", "recommendation_logger.py")


def test_report_context_status_warns_when_sqlite_fallback_is_used():
    warning = pgpipe.fallback_warning("scanner_results", "Postgres unavailable during pytest")
    assert "POSTGRES_PRIMARY_FALLBACK" in warning
    assert "scanner_results" in warning
    assert "stale SQLite compatibility" in warning
