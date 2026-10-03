#!/usr/bin/env python3
"""Daily recommendation-engine summary for Wolfy.

Read-only status synthesis. This script does not create recommendations, paper
trades, broker orders, or live execution.
"""
from __future__ import annotations

import argparse
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
import json
from typing import Any, Mapping

from visible_progress_ledger import DEFAULT_DSN, collect_progress


def _value(mapping: Mapping[str, Any], key: str, default: Any = "n/a") -> Any:
    value = mapping.get(key)
    return default if value is None else value


def _items(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _reasons(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _risk_percent(value: object) -> str:
    try:
        risk = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return "n/a"
    if not risk.is_finite() or risk < 0:
        return "n/a"
    return f"{(risk * Decimal('100')).normalize()}%"


def _leg_symbol(value: object) -> str:
    if not isinstance(value, Mapping):
        return "missing-leg"
    symbol = value.get("symbol")
    return str(symbol) if isinstance(symbol, str) and symbol else "missing-leg"


def _format_instrument(item: Mapping[str, Any]) -> str:
    expression = item.get("expression") or item.get("instrument_expression")
    if expression == "long_call":
        return f"long call {_leg_symbol(item.get('long_leg'))}"
    if expression == "call_debit_spread":
        return (
            f"call debit spread {_leg_symbol(item.get('long_leg'))} / "
            f"{_leg_symbol(item.get('short_leg'))}"
        )
    if expression == "underlying_stock_fallback":
        reasons = _reasons(item.get("fallback_reasons"))
        reason = ", ".join(reasons) if reasons else "no_safe_option_structure"
        return f"underlying stock fallback ({reason})"
    return "instrument decision missing"


def _build_pivot_summary(pivot: Mapping[str, Any]) -> str:
    """Render only actionable pivot output or a meaningful terminal/blocker state."""
    signal_dt = _value(pivot, "signal_dt", "unknown")
    status = str(pivot.get("status") or "pipeline_incomplete")
    broker_orders = pivot.get("broker_orders_created")
    canary_safety_ok = status != "paper_canary_complete" or (
        pivot.get("canary") is True
        and pivot.get("rollback_ready") is True
        and pivot.get("production_schedule_authorized") is False
    )
    safety_ok = (
        pivot.get("paper_only") is True
        and pivot.get("no_live_execution") is True
        and type(broker_orders) is int
        and broker_orders == 0
        and canary_safety_ok
    )
    lines = [f"Wolfy mid/small-cap pivot — signal date: {signal_dt}"]
    if not safety_ok:
        lines.append("SAFETY BLOCKER — paper/no-live invariants are absent or false; do not publish.")
        lines.append(
            f"paper-only: {pivot.get('paper_only')} | "
            f"no live execution: {pivot.get('no_live_execution')} | broker orders: {broker_orders}"
        )
        return "\n".join(lines)

    recommendations = _items(pivot.get("recommendations"))
    writer_blocked = _items(pivot.get("writer_blocked"))
    if status == "paper_canary_complete" and pivot.get("canary") is True:
        lines.append("BOUNDED PAPER-ONLY CANARY — approved breakout only")
        lines.append(
            "rollback ready: "
            f"{'yes' if pivot.get('rollback_ready') is True else 'no'} | "
            "scheduled publisher: "
            f"{'enabled' if pivot.get('production_schedule_authorized') is True else 'disabled'}"
        )
    if status == "pipeline_incomplete":
        reasons = _reasons(pivot.get("incomplete_reasons")) or ["unspecified_incomplete_stage"]
        lines.append(f"PIPELINE INCOMPLETE — {', '.join(reasons)}")
    elif recommendations:
        lines.append(f"PAPER RECOMMENDATIONS — {len(recommendations)}")
        for item in sorted(recommendations, key=lambda row: int(row.get("global_rank", 10**9))):
            lines.append(
                f"#{_value(item, 'global_rank')} {_value(item, 'ticker')} | "
                f"{_value(item, 'strategy')} | {_value(item, 'sector')} | "
                f"entry {_value(item, 'entry')} / stop {_value(item, 'stop')} / "
                f"target {_value(item, 'target')} | risk {_risk_percent(item.get('risk_fraction'))} / "
                f"max loss ${_value(item, 'max_loss')} | {_format_instrument(item)}"
            )
    elif status in {"no_candidates", "no_new_recommendations"}:
        lines.append("NO TRADE — no eligible setup passed")
    elif status == "allocation_blocked":
        cap_reasons = [
            str(row.get("reason"))
            for row in writer_blocked
            if row.get("reason")
            in {"global_position_cap", "aggregate_risk_cap", "sector_position_cap"}
        ]
        count = pivot.get("allocation_blocked", len(writer_blocked))
        if cap_reasons:
            lines.append(f"CAP FULL — {count} candidate(s) blocked: {', '.join(cap_reasons)}")
        else:
            lines.append(f"ALLOCATION BLOCKED — {count} candidate(s)")
    else:
        lines.append(f"PIPELINE INCOMPLETE — unsupported terminal status: {status}")
    lines.append("paper-only; no live execution; broker orders: 0")
    return "\n".join(lines)


def build_daily_summary(data: Mapping[str, Any]) -> str:
    pg = data.get("postgres", {}) if isinstance(data.get("postgres"), Mapping) else {}
    pivot = pg.get("mid_small_pivot")
    if isinstance(pivot, Mapping):
        return _build_pivot_summary(pivot)
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
