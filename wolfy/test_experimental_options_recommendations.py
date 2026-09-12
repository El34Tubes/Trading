from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import pytest

from test_db import test_connection


def test_research_only_options_signal_can_create_explicit_experimental_recommendation():
    pytest.importorskip("psycopg")
    from eod_signals import ensure_signal_schema, seed_default_strategies, write_experimental_options_recommendations

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
    with test_connection() as conn:
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
    pytest.importorskip("psycopg")
    from eod_signals import ensure_signal_schema, seed_default_strategies, write_experimental_options_recommendations
    signal_dt = date(2099, 3, 4)
    ticker = "ZZNOOPT"
    with test_connection() as conn:
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


def _v2_evaluation(ticker: str, *, max_loss: str | None = None, exact: bool = True) -> dict:
    from options_structure_selector import aggressive_options_v2_policy, select_bullish_option_structure

    contracts = [
        {
            "symbol": f"{ticker}LONG", "option_type": "call", "expiration": "2099-03-20", "strike": "100",
            "bid": "2.0", "ask": "2.2", "open_interest": 10, "volume": 1,
            "quote_at": "2099-03-05T20:00:00Z", "multiplier": 100, "standard_contract": True,
        },
        {
            "symbol": f"{ticker}SHORT", "option_type": "call", "expiration": "2099-03-20", "strike": "110",
            "bid": "0.4", "ask": "0.5", "open_interest": 10, "volume": 1,
            "quote_at": "2099-03-05T20:00:00Z", "multiplier": 100, "standard_contract": True,
        },
    ]
    evaluation = select_bullish_option_structure(
        ticker=ticker, underlying_price=Decimal("100"), technical_target=Decimal("105"),
        as_of=date(2099, 3, 5), contracts=contracts,
        policy=aggressive_options_v2_policy(decision_time=datetime(2099, 3, 5, 20, 5, tzinfo=timezone.utc)),
    )
    if max_loss is not None:
        evaluation["selected"]["max_loss_per_contract"] = Decimal(max_loss)
    if not exact:
        evaluation["selected"]["short_leg"] = None
    return evaluation


def test_aggressive_v2_writer_requires_exact_authorized_structure_and_emits_safety_metadata():
    pytest.importorskip("psycopg")
    from eod_signals import seed_default_strategies, write_experimental_options_recommendations

    signal_dt = date(2099, 3, 5)
    ticker = "ZZAGGWRITE"
    with test_connection() as conn:
        seed_default_strategies(conn)
        strategy_id = conn.execute("SELECT id FROM strategies WHERE name='liquid_rs_breakout_aggressive_options_v2'").fetchone()[0]
        try:
            conn.execute(
                """INSERT INTO signals(ticker,dt,strategy_id,direction,raw) VALUES (%s,%s,%s,'long',%s::jsonb)
                   ON CONFLICT(ticker,dt,strategy_id) DO UPDATE SET raw=EXCLUDED.raw""",
                (ticker, signal_dt, strategy_id,
                 '{"close":"100","invalidation":"96","target_r":"1.25","instrument_policy":"defined_risk_options_only","equity_fallback":false,"experimental_forward_recommendations_allowed":true,"strategy_validated":false,"paper_only":true,"no_live_execution":true,"selector_policy_version":"aggressive_options_v2"}'),
            )
            result = write_experimental_options_recommendations(
                conn, signal_dt=signal_dt, option_evaluations={ticker: _v2_evaluation(ticker)},
                strategy_name="liquid_rs_breakout_aggressive_options_v2",
                account_equity_usd=Decimal("5000"), risk_fraction=Decimal("0.05"),
            )
            row = conn.execute("SELECT recommendation_type,status,holding_period,notes FROM recommendations WHERE ticker=%s", (ticker,)).fetchone()
        finally:
            conn.execute("DELETE FROM recommendations WHERE ticker=%s", (ticker,))
            conn.execute("DELETE FROM signals WHERE ticker=%s", (ticker,))

    assert result["recommendations_created"] == 1
    assert row[0] == "experimental_defined_risk_option"
    assert row[1] == "paper_candidate"
    assert row[2] == "Up to 7 trading days"
    assert row[3]["paper_only"] is True
    assert row[3]["no_live_execution"] is True
    assert row[3]["broker_order_submitted"] is False
    assert row[3]["equity_fallback"] is False
    assert row[3]["experimental_forward_test"] is True
    assert row[3]["experimental_forward_recommendations_allowed"] is True
    assert row[3]["strategy_validated"] is False
    assert row[3]["selector_policy_version"] == "aggressive_options_v2"
    assert row[3]["instrument_policy"] == "defined_risk_options_only"
    assert row[3]["option_structure"]["short_leg"]["symbol"] == f"{ticker}SHORT"


def test_aggressive_v2_writer_rejects_over_five_percent_risk_and_inexact_structure():
    pytest.importorskip("psycopg")
    from eod_signals import seed_default_strategies, write_experimental_options_recommendations

    signal_dt = date(2099, 3, 5)
    tickers = ["ZZAGGRISK", "ZZAGGINEXACT"]
    with test_connection() as conn:
        seed_default_strategies(conn)
        strategy_id = conn.execute("SELECT id FROM strategies WHERE name='liquid_rs_breakout_aggressive_options_v2'").fetchone()[0]
        try:
            for ticker in tickers:
                conn.execute(
                    """INSERT INTO signals(ticker,dt,strategy_id,direction,raw) VALUES (%s,%s,%s,'long',
                       '{"close":"100","invalidation":"96","target_r":"1.25","instrument_policy":"defined_risk_options_only","equity_fallback":false,"experimental_forward_recommendations_allowed":true,"strategy_validated":false,"paper_only":true,"no_live_execution":true,"selector_policy_version":"aggressive_options_v2"}'::jsonb)
                       ON CONFLICT DO NOTHING""", (ticker, signal_dt, strategy_id),
                )
            result = write_experimental_options_recommendations(
                conn, signal_dt=signal_dt,
                option_evaluations={tickers[0]: _v2_evaluation(tickers[0], max_loss="250.01"), tickers[1]: _v2_evaluation(tickers[1], exact=False)},
                strategy_name="liquid_rs_breakout_aggressive_options_v2", account_equity_usd=Decimal("5000"), risk_fraction=Decimal("0.20"),
            )
            count = conn.execute("SELECT count(*) FROM recommendations WHERE ticker=ANY(%s)", (tickers,)).fetchone()[0]
        finally:
            conn.execute("DELETE FROM recommendations WHERE ticker=ANY(%s)", (tickers,))
            conn.execute("DELETE FROM signals WHERE ticker=ANY(%s)", (tickers,))

    assert result["recommendations_created"] == 0
    assert result["blocked_by_option_quality"] == 2
    assert count == 0


def test_aggressive_v2_writer_recomputes_and_rejects_forged_evaluations():
    pytest.importorskip("psycopg")
    from eod_signals import seed_default_strategies, write_experimental_options_recommendations

    signal_dt = date(2099, 3, 5)
    tickers = ["ZZFORGENORAW", "ZZFORGESTALE", "ZZFORGELOSS", "ZZFORGENEG"]
    evaluations = {ticker: _v2_evaluation(ticker) for ticker in tickers}
    evaluations[tickers[0]].pop("input_contracts")
    evaluations[tickers[1]]["input_contracts"][0]["quote_at"] = "2099-03-05T18:00:00Z"
    evaluations[tickers[2]]["selected"]["max_loss_per_contract"] = Decimal("1")
    evaluations[tickers[3]]["input_contracts"][0]["strike"] = "-100"
    with test_connection() as conn:
        seed_default_strategies(conn)
        strategy_id = conn.execute("SELECT id FROM strategies WHERE name='liquid_rs_breakout_aggressive_options_v2'").fetchone()[0]
        try:
            for ticker in tickers:
                conn.execute(
                    """INSERT INTO signals(ticker,dt,strategy_id,direction,raw) VALUES (%s,%s,%s,'long',
                       '{"close":"100","invalidation":"96","target_r":"1.25","instrument_policy":"defined_risk_options_only","equity_fallback":false,"experimental_forward_recommendations_allowed":true,"strategy_validated":false,"paper_only":true,"no_live_execution":true,"selector_policy_version":"aggressive_options_v2"}'::jsonb)
                       ON CONFLICT DO NOTHING""", (ticker, signal_dt, strategy_id),
                )
            result = write_experimental_options_recommendations(
                conn, signal_dt=signal_dt, option_evaluations=evaluations,
                strategy_name="liquid_rs_breakout_aggressive_options_v2",
            )
            count = conn.execute("SELECT count(*) FROM recommendations WHERE ticker=ANY(%s)", (tickers,)).fetchone()[0]
        finally:
            conn.execute("DELETE FROM recommendations WHERE ticker=ANY(%s)", (tickers,))
            conn.execute("DELETE FROM signals WHERE ticker=ANY(%s)", (tickers,))
    assert result["recommendations_created"] == 0
    assert result["blocked_by_option_quality"] == 4
    assert count == 0


def test_aggressive_v2_allows_multiple_contracts_with_total_loss_within_five_percent():
    pytest.importorskip("psycopg")
    from eod_signals import seed_default_strategies, write_experimental_options_recommendations

    signal_dt = date(2099, 3, 5)
    ticker = "ZZMULTIRISK"
    with test_connection() as conn:
        seed_default_strategies(conn)
        strategy_id = conn.execute("SELECT id FROM strategies WHERE name='liquid_rs_breakout_aggressive_options_v2'").fetchone()[0]
        try:
            conn.execute(
                """INSERT INTO signals(ticker,dt,strategy_id,direction,raw) VALUES (%s,%s,%s,'long',
                   '{"close":"100","invalidation":"96","target_r":"1.25","instrument_policy":"defined_risk_options_only","equity_fallback":false,"experimental_forward_recommendations_allowed":true,"strategy_validated":false,"paper_only":true,"no_live_execution":true,"selector_policy_version":"aggressive_options_v2"}'::jsonb)
                   ON CONFLICT DO NOTHING""", (ticker, signal_dt, strategy_id),
            )
            result = write_experimental_options_recommendations(
                conn, signal_dt=signal_dt, option_evaluations={ticker: _v2_evaluation(ticker)},
                strategy_name="liquid_rs_breakout_aggressive_options_v2",
                account_equity_usd=Decimal("10000"), risk_fraction=Decimal("0.20"),
            )
            notes = conn.execute("SELECT notes FROM recommendations WHERE ticker=%s", (ticker,)).fetchone()[0]
        finally:
            conn.execute("DELETE FROM recommendations WHERE ticker=%s", (ticker,))
            conn.execute("DELETE FROM signals WHERE ticker=%s", (ticker,))
    assert result["recommendations_created"] == 1
    assert notes["risk_fraction"] == "0.05"
    assert notes["paper_contracts"] > 1
    assert Decimal(notes["total_max_loss_usd"]) <= Decimal(notes["paper_risk_budget_usd"])
    assert Decimal(notes["max_loss_per_contract_usd"]) * notes["paper_contracts"] == Decimal(notes["total_max_loss_usd"])


def test_experimental_recommendation_schema_has_canonical_partial_unique_index():
    pytest.importorskip("psycopg")
    from eod_signals import ensure_signal_schema

    with test_connection() as conn:
        ensure_signal_schema(conn)
        indexdef = conn.execute(
            "SELECT indexdef FROM pg_indexes WHERE tablename='recommendations' AND indexname='uq_experimental_paper_recommendation_signal'"
        ).fetchone()
    assert indexdef is not None
    assert "UNIQUE INDEX" in indexdef[0]
    assert "notes ->> 'signal_dt'" in indexdef[0]
    assert "notes ->> 'strategy_name'" in indexdef[0]


def test_aggressive_v2_global_daily_cap_applies_across_disjoint_calls():
    pytest.importorskip("psycopg")
    from eod_signals import seed_default_strategies, write_experimental_options_recommendations

    signal_dt = date(2099, 3, 5)
    tickers = [f"ZZGLOBAL{i}" for i in range(4)]
    with test_connection() as conn:
        seed_default_strategies(conn)
        strategy_id = conn.execute("SELECT id FROM strategies WHERE name='liquid_rs_breakout_aggressive_options_v2'").fetchone()[0]
        try:
            for ticker in tickers:
                conn.execute(
                    """INSERT INTO signals(ticker,dt,strategy_id,direction,raw) VALUES (%s,%s,%s,'long',
                       '{"close":"100","invalidation":"96","target_r":"1.25","instrument_policy":"defined_risk_options_only","equity_fallback":false,"experimental_forward_recommendations_allowed":true,"strategy_validated":false,"paper_only":true,"no_live_execution":true,"selector_policy_version":"aggressive_options_v2"}'::jsonb)
                       ON CONFLICT DO NOTHING""", (ticker, signal_dt, strategy_id),
                )
            first = write_experimental_options_recommendations(
                conn, signal_dt=signal_dt,
                option_evaluations={ticker: _v2_evaluation(ticker) for ticker in tickers[:3]},
                strategy_name="liquid_rs_breakout_aggressive_options_v2",
            )
            second = write_experimental_options_recommendations(
                conn, signal_dt=signal_dt,
                option_evaluations={tickers[3]: _v2_evaluation(tickers[3])},
                strategy_name="liquid_rs_breakout_aggressive_options_v2",
            )
        finally:
            conn.execute("DELETE FROM recommendations WHERE ticker=ANY(%s)", (tickers,))
            conn.execute("DELETE FROM signals WHERE ticker=ANY(%s)", (tickers,))
    assert first["recommendations_created"] == 3
    assert first["recommendations_ranked"] == 3
    assert second["recommendations_created"] == 0
    assert second["recommendations_ranked"] == 0
