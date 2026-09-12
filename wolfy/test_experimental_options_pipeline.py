from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from test_db import test_connection


def test_pipeline_selects_persists_and_writes_experimental_recommendation():
    pytest.importorskip("psycopg")
    from eod_signals import ensure_signal_schema, seed_default_strategies
    from experimental_options_pipeline import evaluate_and_write_experimental_options
    signal_dt = date(2099, 3, 5)
    ticker = "ZZPIPE"
    chain = [
        {"symbol":"ZZPIPELONG","option_type":"call","expiration":"2099-03-20","strike":"100","bid":"2.0","ask":"2.1","open_interest":500,"volume":50,"implied_volatility":"0.4","quote_at":"2099-03-05T20:00:00Z","multiplier":100,"standard_contract":True},
        {"symbol":"ZZPIPESHORT","option_type":"call","expiration":"2099-03-20","strike":"105","bid":"0.7","ask":"0.8","open_interest":500,"volume":50,"implied_volatility":"0.4","quote_at":"2099-03-05T20:00:00Z","multiplier":100,"standard_contract":True},
    ]
    with test_connection() as conn:
        ensure_signal_schema(conn)
        seed_default_strategies(conn)
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
    pytest.importorskip("psycopg")
    from experimental_options_pipeline import evaluate_and_write_experimental_options
    with test_connection() as conn:
        result = evaluate_and_write_experimental_options(conn, signal_dt=date(2099,3,6), chain_snapshots={}, fetched_at=datetime(2099,3,6,20,tzinfo=timezone.utc), source="unit-read-only")
        assert result["evaluated"] == 0
        assert result["recommendation_result"]["recommendations_created"] == 0
        assert result["missing_chain"] >= 0


def test_pipeline_rejects_unknown_profile():
    from experimental_options_pipeline import resolve_options_profile

    with pytest.raises(ValueError, match="unknown options profile"):
        resolve_options_profile("v3", decision_time=datetime.now(timezone.utc))


def test_v2_pipeline_uses_exact_strategy_policy_ledger_and_recommendation():
    pytest.importorskip("psycopg")
    from eod_signals import ensure_signal_schema, seed_default_strategies
    from experimental_options_pipeline import evaluate_and_write_experimental_options

    signal_dt = date(2099, 3, 7)
    decision_time = datetime(2099, 3, 7, 20, 5, tzinfo=timezone.utc)
    ticker = "ZZPIPEV2"
    chain = [
        {"symbol": "ZZPIPEV2L", "option_type": "call", "expiration": "2099-03-20", "strike": "100", "bid": "2.0", "ask": "2.1", "open_interest": 10, "volume": 1, "quote_at": "2099-03-07T20:00:00Z", "multiplier": 100, "standard_contract": True},
        {"symbol": "ZZPIPEV2S", "option_type": "call", "expiration": "2099-03-20", "strike": "105", "bid": "0.7", "ask": "0.8", "open_interest": 10, "volume": 1, "quote_at": "2099-03-07T20:00:00Z", "multiplier": 100, "standard_contract": True},
    ]
    raw = '{"close":"100","invalidation":"96","target_r":"1.25","instrument_policy":"defined_risk_options_only","equity_fallback":false,"experimental_forward_recommendations_allowed":true,"strategy_validated":false,"paper_only":true,"no_live_execution":true,"selector_policy_version":"aggressive_options_v2"}'
    strategy = "liquid_rs_breakout_aggressive_options_v2"
    with test_connection() as conn:
        ensure_signal_schema(conn)
        seed_default_strategies(conn)
        sid = conn.execute("SELECT id FROM strategies WHERE name=%s", (strategy,)).fetchone()[0]
        try:
            conn.execute("INSERT INTO signals(ticker,dt,strategy_id,direction,raw) VALUES (%s,%s,%s,'long',%s::jsonb) ON CONFLICT(ticker,dt,strategy_id) DO UPDATE SET raw=EXCLUDED.raw", (ticker, signal_dt, sid, raw))
            result = evaluate_and_write_experimental_options(
                conn, signal_dt=signal_dt, chain_snapshots={ticker: chain}, fetched_at=decision_time,
                decision_time=decision_time, source="unit-read-only", profile="aggressive-v2",
            )
            ledger = conn.execute("SELECT strategy_name,evaluation FROM option_structure_evaluations WHERE ticker=%s", (ticker,)).fetchone()
            recommendation = conn.execute("SELECT notes FROM recommendations WHERE ticker=%s", (ticker,)).fetchone()
        finally:
            conn.execute("DELETE FROM recommendations WHERE ticker=%s", (ticker,))
            conn.execute("DELETE FROM option_structure_evaluations WHERE ticker=%s", (ticker,))
            conn.execute("DELETE FROM signals WHERE ticker=%s", (ticker,))
    assert result["profile"] == "aggressive-v2"
    assert result["strategy_name"] == strategy
    assert result["recommendation_result"]["recommendations_created"] == 1
    assert ledger[0] == strategy
    assert ledger[1]["policy"]["policy_version"] == "aggressive_options_v2"
    assert ledger[1]["input_contracts"]
    assert recommendation[0]["strategy_name"] == strategy
