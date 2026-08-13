from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest


def test_research_only_options_signal_can_create_explicit_experimental_recommendation():
    psycopg = pytest.importorskip("psycopg")
    from eod_signals import ensure_signal_schema, seed_default_strategies, write_experimental_options_recommendations

    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    signal_dt = date(2099, 3, 3)
    ticker = "ZZEXPOPT"
    evaluation = {
        "status": "selected",
        "selected": {
            "structure": "call_debit_spread", "expiration": "2099-03-20", "dte": 17,
            "long_leg": {"symbol": "ZZLONG", "strike": "100", "bid": "2", "ask": "2.2"},
            "short_leg": {"symbol": "ZZSHORT", "strike": "110", "bid": "0.4", "ask": "0.5"},
            "conservative_debit": "1.80", "max_loss_per_contract": "180",
            "max_profit_per_contract": "820", "defined_risk": True,
        },
    }
    with psycopg.connect(dsn) as conn:
        ensure_signal_schema(conn)
        seed_default_strategies(conn)
        strategy_id = conn.execute("SELECT id FROM strategies WHERE name='liquid_rs_breakout_options_volatility_v1'").fetchone()[0]
        try:
            conn.execute("""
                INSERT INTO signals(ticker,dt,strategy_id,direction,raw)
                VALUES (%s,%s,%s,'long',%s::jsonb)
                ON CONFLICT(ticker,dt,strategy_id) DO UPDATE SET raw=EXCLUDED.raw
            """, (ticker, signal_dt, strategy_id, '{"close":"100","invalidation":"95","target_r":"1.0","instrument_policy":"defined_risk_options_only"}'))
            first = write_experimental_options_recommendations(
                conn, signal_dt=signal_dt, option_evaluations={ticker: evaluation},
                account_equity_usd=Decimal("5000"), risk_fraction=Decimal("0.05"), dry_run=False,
            )
            second = write_experimental_options_recommendations(
                conn, signal_dt=signal_dt, option_evaluations={ticker: evaluation},
                account_equity_usd=Decimal("5000"), risk_fraction=Decimal("0.05"), dry_run=False,
            )
            row = conn.execute("SELECT recommendation_type,status,notes FROM recommendations WHERE ticker=%s AND notes->>'signal_dt'=%s AND notes->>'strategy_name'='liquid_rs_breakout_options_volatility_v1'", (ticker, signal_dt.isoformat())).fetchone()
            assert first["recommendations_created"] == 1
            assert second["skipped_existing"] == 1
            assert row[0] == "experimental_defined_risk_option"
            assert row[1] == "paper_candidate"
            assert row[2]["experimental_forward_test"] is True
            assert row[2]["strategy_validated"] is False
            assert row[2]["paper_only"] is True
            assert row[2]["no_live_execution"] is True
            assert row[2]["broker_order_submitted"] is False
            assert row[2]["equity_fallback"] is False
            assert row[2]["option_structure"]["structure"] == "call_debit_spread"
            assert row[2]["paper_contracts"] == 1
        finally:
            conn.execute("DELETE FROM recommendations WHERE ticker=%s", (ticker,))
            conn.execute("DELETE FROM signals WHERE ticker=%s", (ticker,))


def test_experimental_writer_does_not_recommend_when_selector_rejects_all_options():
    psycopg = pytest.importorskip("psycopg")
    from eod_signals import ensure_signal_schema, seed_default_strategies, write_experimental_options_recommendations
    dsn = "dbname=wolfy user=root host=/var/run/postgresql"
    signal_dt = date(2099, 3, 4)
    ticker = "ZZNOOPT"
    with psycopg.connect(dsn) as conn:
        ensure_signal_schema(conn)
        seed_default_strategies(conn)
        strategy_id = conn.execute("SELECT id FROM strategies WHERE name='liquid_rs_breakout_options_volatility_v1'").fetchone()[0]
        try:
            conn.execute("INSERT INTO signals(ticker,dt,strategy_id,direction,raw) VALUES (%s,%s,%s,'long','{\"close\":\"100\",\"invalidation\":\"95\"}'::jsonb) ON CONFLICT DO NOTHING", (ticker, signal_dt, strategy_id))
            result = write_experimental_options_recommendations(conn, signal_dt=signal_dt, option_evaluations={ticker: {"status": "no_tradable_option_structure", "selected": None}}, dry_run=False)
            assert result["recommendations_created"] == 0
            assert result["blocked_by_option_quality"] == 1
        finally:
            conn.execute("DELETE FROM recommendations WHERE ticker=%s", (ticker,))
            conn.execute("DELETE FROM signals WHERE ticker=%s", (ticker,))
