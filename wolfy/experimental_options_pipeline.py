"""End-to-end paper-only option structure evaluation for qualifying signals."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping, Sequence

from eod_signals import write_experimental_options_recommendations
from options_research_ledger import store_options_structure_evaluation
from options_structure_selector import SelectorPolicy, select_bullish_option_structure

STRATEGY = "liquid_rs_breakout_options_volatility_v1"


def evaluate_and_write_experimental_options(
    conn, *, signal_dt: date,
    chain_snapshots: Mapping[str, Sequence[Mapping[str, Any]]],
    fetched_at: datetime, source: str, policy: SelectorPolicy | None = None,
    max_recommendations: int = 3, account_equity_usd: Decimal = Decimal("5000"),
    risk_fraction: Decimal = Decimal("0.05"), dry_run: bool = False,
) -> dict[str, Any]:
    rows = conn.execute("""
        SELECT s.ticker,s.raw FROM signals s JOIN strategies st ON st.id=s.strategy_id
        WHERE s.dt=%s AND st.name=%s AND lower(coalesce(s.direction,'')) IN ('long','buy')
        ORDER BY s.ticker
    """, (signal_dt, STRATEGY)).fetchall()
    evaluations: dict[str, Any] = {}
    missing_chain = 0
    selected_count = 0
    for ticker, raw in rows:
        symbol = str(ticker).upper()
        chain = chain_snapshots.get(symbol) or chain_snapshots.get(str(ticker))
        if not chain:
            missing_chain += 1
            continue
        raw = raw or {}
        entry = Decimal(str(raw.get("close") or 0))
        stop = Decimal(str(raw.get("invalidation") or 0))
        target_r = Decimal(str(raw.get("target_r") or 1))
        target = entry + max(entry - stop, Decimal("0")) * target_r
        evaluation = select_bullish_option_structure(
            ticker=symbol, underlying_price=entry, technical_target=target,
            as_of=signal_dt, contracts=chain, policy=policy,
        )
        evaluations[symbol] = evaluation
        if evaluation.get("selected"):
            selected_count += 1
        if not dry_run:
            store_options_structure_evaluation(
                conn, ticker=symbol, signal_dt=signal_dt, strategy_name=STRATEGY,
                underlying_price=entry, technical_target=target,
                fetched_at=fetched_at, source=source, chain=chain, evaluation=evaluation,
            )
    rec_result = write_experimental_options_recommendations(
        conn, signal_dt=signal_dt, option_evaluations=evaluations,
        max_recommendations=max_recommendations, account_equity_usd=account_equity_usd,
        risk_fraction=risk_fraction, dry_run=dry_run,
    )
    return {
        "signal_dt": signal_dt.isoformat(), "evaluated": len(evaluations),
        "selected": selected_count, "missing_chain": missing_chain,
        "paper_only": True, "no_live_execution": True,
        "recommendation_result": rec_result,
    }
