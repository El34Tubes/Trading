from __future__ import annotations

import json

import pytest

from test_db import test_connection


ALPHA_TABLES = (
    "alpha_search_reports",
    "alpha_leads",
    "alpha_lead_evidence",
    "alpha_handoffs",
)


def test_alpha_import_identifier_aliases_exist_and_sync_both_directions():
    pytest.importorskip("psycopg")
    with test_connection() as conn:
        columns = conn.execute(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema='public'
              AND table_name = ANY(%s)
              AND column_name IN ('legacy_id', 'sqlite_id')
            ORDER BY table_name, column_name
            """,
            (list(ALPHA_TABLES),),
        ).fetchall()
        found = {table: set() for table in ALPHA_TABLES}
        for table, column in columns:
            found[table].add(column)
        assert found == {
            table: {"legacy_id", "sqlite_id"} for table in ALPHA_TABLES
        }

        report = conn.execute(
            """
            INSERT INTO alpha_search_reports(
              legacy_id, source_job_id, title, summary
            ) VALUES (%s, 'schema-compat-test', 'legacy alias test', 'rollback fixture')
            RETURNING legacy_id, sqlite_id
            """,
            (9_106_100_801,),
        ).fetchone()
        assert report == (9_106_100_801, 9_106_100_801)

        lead = conn.execute(
            """
            INSERT INTO alpha_leads(
              sqlite_id, ticker, lead_type, title, thesis, source_fingerprint
            ) VALUES (%s, 'ZZIDC', 'test', 'sqlite alias test', 'rollback fixture', %s)
            RETURNING legacy_id, sqlite_id
            """,
            (9_106_100_802, "schema-compat-alpha-id-9106100802"),
        ).fetchone()
        assert lead == (9_106_100_802, 9_106_100_802)


def test_run_ledger_malformed_numeric_json_fails_closed_to_null():
    pytest.importorskip("psycopg")
    detail = {
        "source": "schema-compat-test",
        "rows_written": "not-a-number",
        "rows_upserted": "12.5",
        "feature_rows_upserted": "unknown",
        "bars_loaded": "NaN",
        "tickers_processed": "?",
    }
    with test_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO runs(job, started, finished, status, detail)
            VALUES ('eod-schema-compat-test', now(), now(), 'ok', %s::jsonb)
            RETURNING id, rows_written
            """,
            (json.dumps(detail),),
        ).fetchone()
        assert row[1] is None
        projected = conn.execute(
            """
            SELECT rows_written, bars_loaded, feature_rows_upserted, tickers_processed
            FROM eod_feature_runs WHERE id=%s
            """,
            (row[0],),
        ).fetchone()
        assert projected == (None, None, None, None)
