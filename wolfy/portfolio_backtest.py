"""Chronological portfolio replay for the approved mid/small-cap paper policy.

The replay deliberately consumes setup outcomes rather than manufacturing market
fills.  It applies the production allocator on every signal date, sizes each
selected position at exactly five percent of then-current paper equity, carries
positions until their declared exit date, and stops permanently at ruin.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import math
import random
from typing import Any, Sequence
import uuid

from orchestration_config import MID_SMALL_PIVOT_POLICY
from portfolio_allocator import ExistingPosition, PortfolioCandidate, allocate_portfolio

_RISK = Decimal(str(MID_SMALL_PIVOT_POLICY.risk_fraction_per_position))
_MAX_RISK = Decimal(str(MID_SMALL_PIVOT_POLICY.maximum_aggregate_risk))
_EXPRESSIONS = {"underlying_stock_fallback", "long_call", "call_debit_spread"}
_Q = Decimal("0.0001")


class PortfolioBacktestError(ValueError):
    """Raised when replay inputs cannot be interpreted without guessing."""


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise PortfolioBacktestError(f"{field} must be a finite decimal")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PortfolioBacktestError(f"{field} must be a finite decimal") from exc
    if not parsed.is_finite():
        raise PortfolioBacktestError(f"{field} must be a finite decimal")
    return parsed


def _text(value: object, field: str, *, uppercase: bool = False) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise PortfolioBacktestError(f"{field} must be canonical non-empty text")
    if uppercase and value != value.upper():
        raise PortfolioBacktestError(f"{field} must be uppercase")
    return value


def _q(value: Decimal) -> str:
    return str(value.quantize(_Q))


@dataclass(frozen=True)
class PortfolioBacktestCandidate:
    """A point-in-time candidate joined to its separately labelled outcome."""

    ticker: str
    strategy_id: str
    strategy_version: int
    sector: str
    score: Decimal
    signal_dt: date
    exit_dt: date
    outcome_r: Decimal
    expression: str
    expression_cost_r: Decimal = Decimal("0")
    regime: str = "unknown"

    def __post_init__(self) -> None:
        _text(self.ticker, "ticker", uppercase=True)
        _text(self.strategy_id, "strategy_id")
        _text(self.sector, "sector")
        _text(self.regime, "regime")
        if not isinstance(self.strategy_version, int) or isinstance(self.strategy_version, bool) or self.strategy_version < 1:
            raise PortfolioBacktestError("strategy_version must be a positive integer")
        if not isinstance(self.signal_dt, date) or not isinstance(self.exit_dt, date):
            raise PortfolioBacktestError("signal_dt and exit_dt must be dates")
        if self.exit_dt < self.signal_dt:
            raise PortfolioBacktestError("exit_dt cannot precede signal_dt")
        if self.expression not in _EXPRESSIONS:
            raise PortfolioBacktestError("expression is not supported")
        score = _decimal(self.score, "score")
        outcome = _decimal(self.outcome_r, "outcome_r")
        cost = _decimal(self.expression_cost_r, "expression_cost_r")
        if cost < 0:
            raise PortfolioBacktestError("expression_cost_r must be nonnegative")
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "outcome_r", outcome)
        object.__setattr__(self, "expression_cost_r", cost)


@dataclass
class _OpenPosition:
    candidate: PortfolioBacktestCandidate
    risk_amount: Decimal


@dataclass(frozen=True)
class _DailyObservation:
    dt: date
    equity_before: Decimal
    equity_after: Decimal
    pnl: Decimal
    risk_fraction: Decimal


def _allocator_candidate(item: PortfolioBacktestCandidate) -> PortfolioCandidate:
    identity = "|".join(
        (
            item.signal_dt.isoformat(),
            item.ticker,
            item.strategy_id,
            str(item.strategy_version),
            item.sector,
            str(item.score),
            item.exit_dt.isoformat(),
            item.expression,
        )
    )
    return PortfolioCandidate(
        candidate_id=uuid.uuid5(uuid.NAMESPACE_URL, f"wolfy-portfolio-backtest:{identity}"),
        universe_snapshot_id=uuid.uuid5(uuid.NAMESPACE_URL, f"wolfy-universe:{item.signal_dt.isoformat()}"),
        ticker=item.ticker,
        strategy_id=item.strategy_id,
        strategy_version=str(item.strategy_version),
        sector=item.sector,
        score=item.score,
        entry=Decimal("1"),
        stop=Decimal("0.95"),
        target=Decimal("1.10"),
    )


def _breakdown(trades: Sequence[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        grouped[str(trade[field])].append(trade)
    return {
        key: {
            "outcomes": len(rows),
            "gross_r": _q(sum((Decimal(row["outcome_r"]) for row in rows), Decimal("0"))),
            "cost_r": _q(sum((Decimal(row["expression_cost_r"]) for row in rows), Decimal("0"))),
            "net_pnl": _q(sum((Decimal(row["pnl"]) for row in rows), Decimal("0"))),
        }
        for key, rows in sorted(grouped.items())
    }


def _longest_loss_streak(trades: Sequence[dict[str, Any]]) -> int:
    longest = current = 0
    for trade in sorted(trades, key=lambda row: (row["exit_dt"], row["ticker"])):
        if Decimal(trade["pnl"]) < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _wilson_interval(successes: int, samples: int) -> tuple[str, str]:
    if samples == 0:
        return "0.0000", "0.0000"
    z = 1.959963984540054
    p = successes / samples
    denominator = 1 + (z * z / samples)
    centre = (p + z * z / (2 * samples)) / denominator
    radius = z * math.sqrt((p * (1 - p) / samples) + (z * z / (4 * samples * samples))) / denominator
    return _q(Decimal(str(max(0.0, centre - radius)))), _q(Decimal(str(min(1.0, centre + radius))))


def _bootstrap_ruin(
    daily_returns: Sequence[Decimal], *, samples: int, block_days: int, seed: int
) -> dict[str, Any]:
    rng = random.Random(seed)
    if not daily_returns or samples == 0:
        return {
            "seed": seed,
            "samples": samples,
            "block_days": block_days,
            "ruined_paths": 0,
            "probability": "0.0000",
            "confidence_interval_95": ["0.0000", "0.0000"],
        }
    blocks = [tuple(daily_returns[index : index + block_days]) for index in range(len(daily_returns))]
    ruined = 0
    horizon = len(daily_returns)
    for _ in range(samples):
        path: list[Decimal] = []
        while len(path) < horizon:
            path.extend(blocks[rng.randrange(len(blocks))])
        equity = Decimal("1")
        for value in path[:horizon]:
            equity *= Decimal("1") + value
            if equity <= 0:
                ruined += 1
                break
    low, high = _wilson_interval(ruined, samples)
    return {
        "seed": seed,
        "samples": samples,
        "block_days": block_days,
        "ruined_paths": ruined,
        "probability": _q(Decimal(ruined) / Decimal(samples)),
        "confidence_interval_95": [low, high],
    }


def run_portfolio_backtest(
    candidates: Sequence[PortfolioBacktestCandidate],
    *,
    starting_equity: Decimal = Decimal("100000"),
    bootstrap_samples: int = 1000,
    block_days: int = 5,
    seed: int = 0,
) -> dict[str, Any]:
    """Replay allocator decisions and report realized and bootstrapped ruin risk."""
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise PortfolioBacktestError("candidates must be a sequence")
    if any(not isinstance(item, PortfolioBacktestCandidate) for item in candidates):
        raise PortfolioBacktestError("every candidate must be a PortfolioBacktestCandidate")
    equity = _decimal(starting_equity, "starting_equity")
    if equity <= 0:
        raise PortfolioBacktestError("starting_equity must be positive")
    if not isinstance(bootstrap_samples, int) or isinstance(bootstrap_samples, bool) or bootstrap_samples < 0:
        raise PortfolioBacktestError("bootstrap_samples must be a nonnegative integer")
    if not isinstance(block_days, int) or isinstance(block_days, bool) or block_days < 1:
        raise PortfolioBacktestError("block_days must be a positive integer")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise PortfolioBacktestError("seed must be an integer")

    ordered = sorted(
        candidates,
        key=lambda item: (
            item.signal_dt,
            item.ticker,
            item.strategy_id,
            item.strategy_version,
            -item.score,
            item.exit_dt,
        ),
    )
    by_signal: dict[date, list[PortfolioBacktestCandidate]] = defaultdict(list)
    for item in ordered:
        by_signal[item.signal_dt].append(item)
    event_dates = sorted({item.signal_dt for item in ordered} | {item.exit_dt for item in ordered})
    open_positions: dict[str, _OpenPosition] = {}
    allocations: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    daily: list[_DailyObservation] = []
    ruin_date: date | None = None
    peak = equity
    max_drawdown = Decimal("0")
    total_risk_observations: list[Decimal] = []

    for current_dt in event_dates:
        equity_before = equity
        exits = sorted(
            (position for position in open_positions.values() if position.candidate.exit_dt == current_dt),
            key=lambda position: (position.candidate.ticker, position.candidate.strategy_id),
        )
        daily_pnl = Decimal("0")
        for position in exits:
            item = position.candidate
            net_r = item.outcome_r - item.expression_cost_r
            pnl = position.risk_amount * net_r
            daily_pnl += pnl
            trades.append(
                {
                    "ticker": item.ticker,
                    "strategy_id": item.strategy_id,
                    "sector": item.sector,
                    "regime": item.regime,
                    "expression": item.expression,
                    "signal_dt": item.signal_dt.isoformat(),
                    "exit_dt": item.exit_dt.isoformat(),
                    "risk_fraction": _q(_RISK),
                    "risk_amount": _q(position.risk_amount),
                    "outcome_r": _q(item.outcome_r),
                    "expression_cost_r": _q(item.expression_cost_r),
                    "net_r": _q(net_r),
                    "pnl": _q(pnl),
                }
            )
            del open_positions[item.ticker]
        equity += daily_pnl
        if equity <= 0 and ruin_date is None:
            equity = Decimal("0")
            ruin_date = current_dt
            open_positions.clear()

        signals_today = by_signal.get(current_dt, [])
        if ruin_date is not None:
            for item in signals_today:
                allocations.append(
                    {
                        "signal_dt": current_dt.isoformat(),
                        "ticker": item.ticker,
                        "strategy_id": item.strategy_id,
                        "selected": False,
                        "reason": "account_ruined",
                        "global_rank": None,
                    }
                )
        elif signals_today:
            source_by_id: dict[uuid.UUID, PortfolioBacktestCandidate] = {}
            allocator_candidates = []
            for item in signals_today:
                converted = _allocator_candidate(item)
                source_by_id[converted.candidate_id] = item
                allocator_candidates.append(converted)
            existing = tuple(
                ExistingPosition(ticker, position.candidate.sector, _RISK)
                for ticker, position in sorted(open_positions.items())
            )
            result = allocate_portfolio(allocator_candidates, existing_positions=existing)
            for decision in result.decisions:
                item = source_by_id[decision.candidate.candidate_id]
                allocations.append(
                    {
                        "signal_dt": current_dt.isoformat(),
                        "ticker": item.ticker,
                        "strategy_id": item.strategy_id,
                        "selected": decision.selected,
                        "reason": decision.reason,
                        "global_rank": decision.global_rank,
                    }
                )
                if decision.selected:
                    open_positions[item.ticker] = _OpenPosition(
                        candidate=item,
                        risk_amount=equity * _RISK,
                    )

        committed_risk = Decimal(len(open_positions)) * _RISK
        if committed_risk > _MAX_RISK:
            raise AssertionError("allocator exceeded aggregate risk policy")
        total_risk_observations.append(committed_risk)
        peak = max(peak, equity)
        drawdown = (equity / peak) - Decimal("1") if peak > 0 else Decimal("-1")
        max_drawdown = min(max_drawdown, drawdown)
        daily.append(
            _DailyObservation(
                dt=current_dt,
                equity_before=equity_before,
                equity_after=equity,
                pnl=daily_pnl,
                risk_fraction=committed_risk,
            )
        )

    daily_returns = [
        observation.pnl / observation.equity_before
        for observation in daily
        if observation.equity_before > 0 and observation.pnl != 0
    ]
    week_pnl: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
    for observation in daily:
        week_start = observation.dt - timedelta(days=observation.dt.weekday())
        week_pnl[week_start] += observation.pnl
    worst_day = min(daily, key=lambda row: (row.pnl, row.dt), default=None)
    worst_week = min(week_pnl.items(), key=lambda row: (row[1], row[0]), default=None)
    elapsed = (ruin_date - event_dates[0]).days if ruin_date is not None and event_dates else None
    bootstrap = _bootstrap_ruin(
        daily_returns, samples=bootstrap_samples, block_days=block_days, seed=seed
    )
    mean_risk = (
        sum(total_risk_observations, Decimal("0")) / Decimal(len(total_risk_observations))
        if total_risk_observations
        else Decimal("0")
    )

    return {
        "policy": {
            "maximum_positions": MID_SMALL_PIVOT_POLICY.maximum_positions,
            "risk_fraction": _q(_RISK),
            "maximum_per_sector": MID_SMALL_PIVOT_POLICY.maximum_positions_per_sector,
            "maximum_aggregate_risk": _q(_MAX_RISK),
        },
        "allocations": allocations,
        "trades": trades,
        "daily": [
            {
                "dt": row.dt.isoformat(),
                "equity_before": _q(row.equity_before),
                "equity_after": _q(row.equity_after),
                "pnl": _q(row.pnl),
                "aggregate_risk_fraction": _q(row.risk_fraction),
            }
            for row in daily
        ],
        "metrics": {
            "starting_equity": _q(_decimal(starting_equity, "starting_equity")),
            "terminal_equity": _q(equity),
            "max_drawdown": _q(max_drawdown),
            "risk_utilization_mean": _q(mean_risk),
            "risk_utilization_max": _q(max(total_risk_observations, default=Decimal("0"))),
            "worst_day": None if worst_day is None else {"date": worst_day.dt.isoformat(), "pnl": _q(worst_day.pnl)},
            "worst_week": None if worst_week is None else {"week_start": worst_week[0].isoformat(), "pnl": _q(worst_week[1])},
            "longest_loss_streak": _longest_loss_streak(trades),
        },
        "ruin": {
            "occurred": ruin_date is not None,
            "date": ruin_date.isoformat() if ruin_date is not None else None,
            "time_to_ruin_days": elapsed,
            "historical_ruin_frequency": "1.0000" if ruin_date is not None else "0.0000",
            "bootstrap": bootstrap,
        },
        "by_strategy": _breakdown(trades, "strategy_id"),
        "by_sector": _breakdown(trades, "sector"),
        "by_regime": _breakdown(trades, "regime"),
        "by_expression": _breakdown(trades, "expression"),
        "outcome_labels_pooled": False,
        "model_limits": (
            "block bootstrap resamples observed daily portfolio P&L; it does not model unseen tails, "
            "changing correlations, liquidity capacity, or execution beyond supplied expression costs"
        ),
        "paper_only": True,
        "no_live_execution": True,
        "broker_orders_created": 0,
    }
