from __future__ import annotations

from recommendation_engine_daily_summary import build_daily_summary


def test_build_daily_summary_reports_recommendation_engine_status_concisely():
    data = {
        "generated_at_utc": "2026-08-11T21:00:00+00:00",
        "postgres": {
            "recommendation_engine": {
                "approved_strategy": "liquid_rs_breakout_close_confirm_1r",
                "approved_strategy_status": "approved",
                "latest_signal_dt": "2026-07-14",
                "approved_strategy_signals": 1086,
                "paper_candidates": 0,
                "paper_logged_recommendations": 1,
                "open_paper_trades": 0,
                "latest_open_trade": None,
                "next_blocked_gate": "daily EOD ingest/signals",
                "live_execution_allowed": False,
            },
            "paper_ledger": {
                "paper_trades_total": 1,
                "open_paper_trades": 0,
                "closed_pnl_total": "250.00",
                "latest_paper_trade_dt": "2026-07-15",
            },
        },
    }

    report = build_daily_summary(data)

    assert "Wolfy Recommendation Engine Daily Summary" in report
    assert "liquid_rs_breakout_close_confirm_1r" in report
    assert "latest signal date: 2026-07-14" in report
    assert "paper logged: 1" in report
    assert "paper trades: 1 total / 0 open" in report
    assert "closed paper PnL: 250.00" in report
    assert "live execution: disabled" in report
    assert "next gate: daily EOD ingest/signals" in report


def _pivot_data(status: str, **overrides):
    pivot = {
        "status": status,
        "signal_dt": "2026-09-16",
        "paper_only": True,
        "no_live_execution": True,
        "broker_orders_created": 0,
        "recommendations": [],
    }
    pivot.update(overrides)
    return {"postgres": {"mid_small_pivot": pivot}}


def test_pivot_summary_distinguishes_incomplete_pipeline_from_no_trade():
    report = build_daily_summary(
        _pivot_data(
            "pipeline_incomplete",
            incomplete_reasons=["benchmark_mdy_missing", "universe_snapshot_stale"],
        )
    )

    assert "PIPELINE INCOMPLETE" in report
    assert "signal date: 2026-09-16" in report
    assert "benchmark_mdy_missing, universe_snapshot_stale" in report
    assert "NO TRADE" not in report
    assert "paper-only; no live execution; broker orders: 0" in report


def test_pivot_summary_calls_a_complete_empty_run_no_trade():
    report = build_daily_summary(_pivot_data("no_candidates"))

    assert "NO TRADE — no eligible setup passed" in report
    assert "PIPELINE INCOMPLETE" not in report


def test_pivot_summary_reports_allocation_blocked_and_cap_full():
    blocked = build_daily_summary(
        _pivot_data("allocation_blocked", allocation_blocked=3)
    )
    full = build_daily_summary(
        _pivot_data(
            "allocation_blocked",
            allocation_blocked=2,
            writer_blocked=[
                {"ticker": "AAAA", "reason": "global_position_cap"},
                {"ticker": "BBBB", "reason": "aggregate_risk_cap"},
            ],
        )
    )

    assert "ALLOCATION BLOCKED — 3 candidate(s)" in blocked
    assert "CAP FULL" in full
    assert "global_position_cap" in full


def test_pivot_summary_formats_exact_option_and_stock_fallback_recommendations():
    report = build_daily_summary(
        _pivot_data(
            "paper_recommendations",
            recommendations=[
                {
                    "ticker": "ABCD",
                    "strategy": "liquid_rs_breakout_close_confirm_1r",
                    "global_rank": 1,
                    "sector": "Industrials",
                    "entry": "20.00",
                    "stop": "19.00",
                    "target": "22.00",
                    "risk_fraction": "0.05",
                    "expression": "call_debit_spread",
                    "max_loss": "400",
                    "long_leg": {"symbol": "ABCD261016C00020000"},
                    "short_leg": {"symbol": "ABCD261016C00022000"},
                },
                {
                    "ticker": "EFGH",
                    "strategy": "liquid_rs_breakout_close_confirm_1r",
                    "global_rank": 2,
                    "sector": "Technology",
                    "entry": "30.00",
                    "stop": "28.50",
                    "target": "33.00",
                    "risk_fraction": "0.05",
                    "expression": "underlying_stock_fallback",
                    "max_loss": "500",
                    "fallback_reasons": ["option_chain_unavailable"],
                },
            ],
        )
    )

    assert "#1 ABCD | liquid_rs_breakout_close_confirm_1r | Industrials" in report
    assert "entry 20.00 / stop 19.00 / target 22.00" in report
    assert "risk 5% / max loss $400" in report
    assert "call debit spread ABCD261016C00020000 / ABCD261016C00022000" in report
    assert "#2 EFGH" in report
    assert "underlying stock fallback (option_chain_unavailable)" in report


def test_pivot_summary_rejects_false_safety_flags():
    report = build_daily_summary(
        _pivot_data("paper_recommendations", broker_orders_created=1)
    )

    assert "SAFETY BLOCKER" in report
    assert "NO TRADE" not in report
