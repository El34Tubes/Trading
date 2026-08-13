from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest


def test_pipeline_selects_persists_and_writes_experimental_recommendation():
    psycopg = pytest.importorskip("psycopg")
    from eod_signals import ensure_signal_schema, seed_default_strategies
    from experimental_options_pipeline import evaluate_and_write_experimental_options
    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    signal_dt = date(2099, 3, 5)
    ticker = "ZZPIPE"
    chain = [
        {"symbol":"ZZPIPELONG","option_type":"call","expiration":"2099-03-20","strike":"100","bid":"2.0","ask":"2.1","open_interest":500,"volume":50,"implied_volatility":"0.4","quote_at":"2099-03-05T20:00:00Z","multiplier":100,"standard_contract":True},
        {"symbol":"ZZPIPESHORT","option_type":"call","expiration":"2099-03-20","strike":"105","bid":"0.7","ask":"0.8","open_interest":500,"volume":50,"implied_volatility":"0.4","quote_at":"2099-03-05T20:00:00Z","multiplier":100,"standard_contract":True},
    ]
    with psycopg.connect(dsn) as conn:
        ensure_signal_schema(conn); seed_default_strategies(conn)
        sid = conn.execute("SELECT id FROM strategies WHERE name='liquid_rs_breakout_options_volatility_v1'").fetchone()[0]
        try:
            conn.execute("INSERT INTO signals(ticker,dt,strategy_id,direction,raw) VALUES (%s,%s,%s,'long','{\"close\":\"100\",\"invalidation\":\"95\",\"target_r\":\"1\"}'::jsonb) ON CONFLICT DO NOTHING", (ticker,signal_dt,sid))
            result = evaluate_and_write_experimental_options(
                conn, signal_dt=signal_dt, chain_snapshots={ticker: chain},
                fetched_at=datetime(2099,3,5,20,tzinfo=timezone.utc), source="unit-read-only",
            )
            assert result["evaluated"] == 1
            assert result["selected"] == 1
            assert result["recommendation_result"]["recommendations_created"] == 1
            assert conn.execute("SELECT count(*) FROM option_structure_evaluations WHERE ticker=%s",(ticker,)).fetchone()[0] == 1
        finally:
            conn.execute("DELETE FROM recommendations WHERE ticker=%s",(ticker,))
            conn.execute("DELETE FROM option_structure_evaluations WHERE ticker=%s",(ticker,))
            conn.execute("DELETE FROM signals WHERE ticker=%s",(ticker,))


def test_pipeline_records_missing_chain_without_fabricating_recommendation():
    psycopg = pytest.importorskip("psycopg")
    from experimental_options_pipeline import evaluate_and_write_experimental_options
    with psycopg.connect("dbname=wolfy user=root host=/var/run/postgresql") as conn:
        result = evaluate_and_write_experimental_options(conn, signal_dt=date(2099,3,6), chain_snapshots={}, fetched_at=datetime(2099,3,6,20,tzinfo=timezone.utc), source="unit-read-only")
        assert result["evaluated"] == 0
        assert result["recommendation_result"]["recommendations_created"] == 0
        assert result["missing_chain"] >= 0
