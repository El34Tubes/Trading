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
