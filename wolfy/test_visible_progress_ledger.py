#!/usr/bin/env python3
"""Regression tests for the read-only Wolfy visible progress ledger."""
from __future__ import annotations

from visible_progress_ledger import render_markdown


def _sample_progress_data() -> dict:
    return {
        "generated_at_utc": "2026-06-26T06:15:00+00:00",
        "eod_constitution": "closing-data only; deterministic gates; no auto-execution; human approval required",
        "constraints": "Robinhood-tradable U.S. stocks/ETFs only, long-only, max 3 positions, stops required, paper-trading orientation",
        "postgres": {
            "counts": {"prices": 10, "strategies": 2, "paper_trades": 1},
            "data_freshness": {
                "latest_price_dt": "2026-06-25",
                "latest_price_tickers": 10,
                "latest_feature_dt": "2026-06-25",
                "latest_feature_tickers": 10,
            },
            "historical_depth": {
                "tickers_with_prices": 10,
                "earliest_first_dt": "2024-06-25",
                "latest_last_dt": "2026-06-25",
                "min_bars": 501,
                "median_bars": 503,
                "tickers_ge_500_bars": 10,
                "tickers_lt_500_bars": 0,
            },
            "scanner_freshness": {"latest_run_id": 42, "latest_data_date": "2026-06-25", "candidate_count": 3},
            "recent_signals": {"latest_signal_dt": "2026-06-25", "latest_signal_count": 2, "seven_day_signal_count": 5},
            "setups": {"total": 0, "open_or_pending": 0, "latest_created_dt": None},
            "positions": {"open_positions": 0, "total_positions": 0},
            "paper_ledger": {
                "paper_trades_total": 1,
                "open_paper_trades": 0,
                "open_paper_trades_without_stop": 0,
                "closed_pnl_total": "12.34",
                "latest_paper_trade_dt": "2026-06-20",
                "recommendations_total": 2,
                "pending_recommendations": 1,
                "pending_recommendations_without_stop": 0,
            },
            "backlog_hygiene": {
                "queued_or_ready": 1,
                "in_progress": 0,
                "blocked": 0,
                "stale_in_progress_gt_6h": 0,
                "duplicate_active_fingerprints": 0,
            },
            "strategies": [
                {
                    "name": "trend_volume_vol_regime",
                    "status": "research_only",
                    "latest_oos_sharpe": None,
                    "latest_oos_verdict": None,
                    "last_validated": None,
                },
                {
                    "name": "sector_cross_sectional_momentum",
                    "status": "candidate",
                    "latest_oos_sharpe": "0.7",
                    "latest_oos_verdict": "survived",
                    "last_validated": "2026-06-25",
                },
            ],
            "latest_backtests": [
                {
                    "name": "sector_cross_sectional_momentum",
                    "backtest_id": 7,
                    "window_start": "2024-01-01",
                    "window_end": "2026-06-25",
                    "is_sharpe": "0.2",
                    "oos_sharpe": "0.7",
                    "oos_cagr": "0.05",
                    "max_dd": "-0.18",
                    "turnover": "1.3",
                    "survives_oos": True,
                    "is_trades": 40,
                    "oos_trades": 12,
                }
            ],
            "strategy_readiness": [
                {
                    "name": "trend_volume_vol_regime",
                    "status": "research_only",
                    "latest_signal_dt": "2026-06-25",
                    "latest_signal_count": 2,
                    "total_signals": 20,
                    "latest_setup_dt": None,
                    "open_or_pending_setups": 0,
                    "gate_note": "candidate/research only; candidate is not approved",
                }
            ],
            "recent_blockers": [],
        },
        "cron": {"active_count": 20, "paused_count": 0, "recent_usage_limit_seen": False},
    }


def test_render_markdown_preserves_eod_and_human_approval_gates() -> None:
    markdown = render_markdown(_sample_progress_data(), blocker_limit=0)

    assert "closing-data only" in markdown
    assert "no auto-execution" in markdown
    assert "human approval required" in markdown
    assert "candidate is not approved" in markdown
    assert "paper/accountability only; no live trading or auto-execution" in markdown
    assert "Next decision target: review sector_cross_sectional_momentum candidate evidence" in markdown


def test_render_markdown_has_core_visibility_sections() -> None:
    markdown = render_markdown(_sample_progress_data(), blocker_limit=0)

    for heading in (
        "## Snapshot",
        "## Strategy gates",
        "## Latest walk-forward validation",
        "## Deterministic strategy readiness",
        "## Paper/accountability gate",
        "## Blockers / noise",
        "## Next recommended action",
    ):
        assert heading in markdown

    assert "latest_price_dt=2026-06-25" in markdown
    assert "paper_trades=1" in markdown
    assert "queued_ready=1" in markdown
