"""End-to-end paper-only option structure evaluation for qualifying signals."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping, Sequence

from eod_signals import write_experimental_options_recommendations
from option_chain_provider import OptionChainSnapshot
from options_research_ledger import store_options_structure_evaluation
from options_structure_selector import (
    SelectorPolicy,
    aggressive_options_v2_policy,
    select_bullish_option_structure,
    strict_mapping_sequence,
)

PROFILE_STRATEGIES = {
    "v1": "liquid_rs_breakout_options_volatility_v1",
    "aggressive-v2": "liquid_rs_breakout_aggressive_options_v2",
}
STRATEGY = PROFILE_STRATEGIES["v1"]


def resolve_options_profile(
    profile: str, *, decision_time: datetime | None
) -> tuple[str, SelectorPolicy]:
    if profile == "v1":
        return PROFILE_STRATEGIES[profile], SelectorPolicy()
    if profile == "aggressive-v2":
        return PROFILE_STRATEGIES[profile], aggressive_options_v2_policy(decision_time=decision_time)
    raise ValueError(f"unknown options profile: {profile!r}")


def evaluate_and_write_experimental_options(
    conn, *, signal_dt: date,
    chain_snapshots: Mapping[
        str, Sequence[Mapping[str, Any]] | OptionChainSnapshot
    ],
    fetched_at: datetime, source: str, policy: SelectorPolicy | None = None,
    profile: str = "v1", decision_time: datetime | None = None,
    max_recommendations: int = 3, account_equity_usd: Decimal = Decimal("5000"),
    risk_fraction: Decimal = Decimal("0.05"), dry_run: bool = False,
) -> dict[str, Any]:
    effective_decision_time = decision_time or fetched_at
    strategy_name, profile_policy = resolve_options_profile(profile, decision_time=decision_time)
    if policy is not None:
        if profile != "v1":
            raise ValueError("custom policy is supported only for the v1 profile")
        profile_policy = policy
    rows = conn.execute("""
        SELECT s.ticker,s.raw FROM signals s JOIN strategies st ON st.id=s.strategy_id
        WHERE s.dt=%s AND st.name=%s AND lower(coalesce(s.direction,'')) IN ('long','buy')
        ORDER BY s.ticker
    """, (signal_dt, strategy_name)).fetchall()
    evaluations: dict[str, Any] = {}
    missing_chain = 0
    selected_count = 0
    for ticker, raw in rows:
        symbol = str(ticker).upper()
        supplied = chain_snapshots.get(symbol) or chain_snapshots.get(str(ticker))
        if not supplied:
            missing_chain += 1
            continue
        exact_snapshot = supplied if isinstance(supplied, OptionChainSnapshot) else None
        if exact_snapshot is not None:
            if exact_snapshot.ticker != symbol:
                raise ValueError("option-chain snapshot ticker mismatch")
            chain = exact_snapshot.chain()
        else:
            chain = list(strict_mapping_sequence(supplied, field="chain snapshot"))
        raw = raw or {}
        entry = Decimal(str(raw.get("close") or 0))
        stop = Decimal(str(raw.get("invalidation") or 0))
        target_r = Decimal(str(raw.get("target_r") or 1))
        target = entry + max(entry - stop, Decimal("0")) * target_r
        evaluation = select_bullish_option_structure(
            ticker=symbol, underlying_price=entry, technical_target=target,
            as_of=signal_dt, contracts=chain, policy=profile_policy,
        )
        if evaluation.get("selected"):
            selected_count += 1
        if not dry_run:
            quote_times = [
                datetime.fromisoformat(str(contract["quote_at"]).replace("Z", "+00:00"))
                for contract in chain
                if contract.get("quote_at") is not None
            ]
            snapshot_fetched_at = exact_snapshot.fetched_at if exact_snapshot else fetched_at
            snapshot_market_at = (
                exact_snapshot.market_at
                if exact_snapshot
                else (max(quote_times) if quote_times else fetched_at)
            )
            snapshot_available_at = exact_snapshot.available_at if exact_snapshot else fetched_at
            snapshot_provider = exact_snapshot.provider if exact_snapshot else source
            snapshot_source_url = exact_snapshot.source_url if exact_snapshot else source
            provenance = store_options_structure_evaluation(
                conn, ticker=symbol, signal_dt=signal_dt, strategy_name=strategy_name,
                underlying_price=entry, technical_target=target,
                decision_at=effective_decision_time, fetched_at=snapshot_fetched_at,
                market_at=snapshot_market_at, available_at=snapshot_available_at,
                provider=snapshot_provider, source_url=snapshot_source_url,
                chain=chain, evaluation=evaluation,
                snapshot_id=exact_snapshot.snapshot_id if exact_snapshot else None,
            )
            evaluation = {**evaluation, **provenance}
        evaluations[symbol] = evaluation
    rec_result = write_experimental_options_recommendations(
        conn, signal_dt=signal_dt, option_evaluations=evaluations,
        max_recommendations=max_recommendations, account_equity_usd=account_equity_usd,
        risk_fraction=risk_fraction, dry_run=dry_run,
        strategy_name=strategy_name,
    )
    return {
        "signal_dt": signal_dt.isoformat(), "profile": profile,
        "strategy_name": strategy_name, "evaluated": len(evaluations),
        "selected": selected_count, "missing_chain": missing_chain,
        "paper_only": True, "no_live_execution": True,
        "recommendation_result": rec_result,
    }
