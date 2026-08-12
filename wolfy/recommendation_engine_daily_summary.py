#!/usr/bin/env python3
"""Daily recommendation-engine summary for Wolfy.

Read-only status synthesis. This script does not create recommendations, paper
trades, broker orders, or live execution.
"""
from __future__ import annotations

import argparse
import json
from typing import Any, Mapping

from visible_progress_ledger import DEFAULT_DSN, collect_progress


def _value(mapping: Mapping[str, Any], key: str, default: Any = "n/a") -> Any:
    value = mapping.get(key)
    return default if value is None else value


def build_daily_summary(data: Mapping[str, Any]) -> str:
    pg = data.get("postgres", {}) if isinstance(data.get("postgres"), Mapping) else {}
    rec = pg.get("recommendation_engine", {}) if isinstance(pg.get("recommendation_engine"), Mapping) else {}
    paper = pg.get("paper_ledger", {}) if isinstance(pg.get("paper_ledger"), Mapping) else {}
    live_enabled = bool(rec.get("live_execution_allowed"))
    lines = [
        f"Wolfy Recommendation Engine Daily Summary — {data.get('generated_at_utc', 'unknown time')}",
        f"strategy: {_value(rec, 'approved_strategy')} ({_value(rec, 'approved_strategy_status')})",
        f"latest signal date: {_value(rec, 'latest_signal_dt')} | approved strategy signals: {_value(rec, 'approved_strategy_signals')}",
        f"paper candidates: {_value(rec, 'paper_candidates', 0)} | paper logged: {_value(rec, 'paper_logged_recommendations', 0)}",
        f"paper trades: {_value(paper, 'paper_trades_total', 0)} total / {_value(paper, 'open_paper_trades', 0)} open | latest trade date: {_value(paper, 'latest_paper_trade_dt')}",
        f"closed paper PnL: {_value(paper, 'closed_pnl_total', '0')}",
        f"latest open trade: {_value(rec, 'latest_open_trade', 'none')}",
        f"next gate: {_value(rec, 'next_blocked_gate')}",
        f"live execution: {'enabled' if live_enabled else 'disabled'}",
        "discipline: paper-only, EOD-only, deterministic strategy source; no broker order is allowed from this summary.",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Print Wolfy recommendation-engine daily summary")
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    parser.add_argument("--json", action="store_true", help="emit raw ledger JSON instead of summary text")
    args = parser.parse_args()
    data = collect_progress(args.dsn)
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True, default=str))
    else:
        print(build_daily_summary(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
