from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from statistics import mean, median, pstdev
from typing import Any, Sequence

from portfolio_backtest import PortfolioBacktestCandidate, run_portfolio_backtest

DEFAULT_DSN = os.environ.get("WOLFY_POSTGRES_DSN", "dbname=wolfy user=root host=/var/run/postgresql")
DEFAULT_SLIPPAGE_BPS = Decimal("10")
DEFAULT_COMMISSION_PER_TRADE = Decimal("0")
DEFAULT_MIN_OOS_SHARPE = Decimal("0.75")
DEFAULT_MIN_IS_TRADES = 60
DEFAULT_MIN_OOS_TRADES = 20
DEFAULT_MAX_OOS_DRAWDOWN = Decimal("0.15")


@dataclass(frozen=True)
class BacktestResult:
    backtest_id: int
    strategy_id: int
    strategy_name: str
    is_sharpe: Decimal
    oos_sharpe: Decimal
    oos_cagr: Decimal
    max_dd: Decimal
    turnover: Decimal
    survives_oos: bool
    trades: int
    oos_trades: int


@dataclass(frozen=True)
class StrategyBacktestSpec:
    """Frozen setup-native backtest identity and execution semantics."""

    strategy_id: str
    strategy_version: int
    entry_mode: str
    split_mode: str
    max_hold_days: int
    preserve_approval: bool = False


@dataclass(frozen=True)
class ChronologicalFold:
    train: tuple[date, ...]
    test: tuple[date, ...]


@dataclass(frozen=True)
class ChronologicalSplits:
    mode: str
    folds: tuple[ChronologicalFold, ...]
    holdout: tuple[date, ...]


_PIVOT_STRATEGIES = {
    "close_confirmed_breakout_v1",
    "mid_small_trend_pullback_reclaim_v1",
    "mid_small_volatility_contraction_breakout_v1",
}


def build_chronological_splits(
    dates: Sequence[date],
    *,
    mode: str,
    train_size: int,
    test_size: int,
    purge_days: int = 0,
    holdout_size: int = 0,
) -> ChronologicalSplits:
    """Create deterministic anchored/rolling folds without opening the holdout."""
    if mode not in {"anchored", "rolling"}:
        raise ValueError("mode must be anchored or rolling")
    if train_size < 1 or test_size < 1 or purge_days < 0 or holdout_size < 0:
        raise ValueError("split sizes must be positive and purge/holdout nonnegative")
    ordered = list(dates)
    if ordered != sorted(ordered) or len(set(ordered)) != len(ordered):
        raise ValueError("dates must be unique and chronological")
    if holdout_size >= len(ordered) and ordered:
        raise ValueError("holdout must leave chronological development data")
    holdout = tuple(ordered[-holdout_size:]) if holdout_size else ()
    development = ordered[:-holdout_size] if holdout_size else ordered
    folds: list[ChronologicalFold] = []
    train_end = train_size
    while train_end + purge_days + test_size <= len(development):
        train_start = 0 if mode == "anchored" else train_end - train_size
        test_start = train_end + purge_days
        folds.append(
            ChronologicalFold(
                train=tuple(development[train_start:train_end]),
                test=tuple(development[test_start : test_start + test_size]),
            )
        )
        train_end += test_size
    return ChronologicalSplits(mode=mode, folds=tuple(folds), holdout=holdout)


def _aware(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be an aware datetime")
    return value


def _finite_decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite decimal")
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise ValueError(f"{field} must be a finite decimal")
    return parsed


def evaluate_setup_trade(
    signal: Mapping[str, Any],
    future_bars: Sequence[Mapping[str, Any]],
    *,
    entry_mode: str,
    slippage_bps: Decimal = DEFAULT_SLIPPAGE_BPS,
    commission: Decimal = DEFAULT_COMMISSION_PER_TRADE,
    delisting_return: Decimal | None = None,
) -> dict[str, Any]:
    """Evaluate a long setup with conservative gap and same-bar assumptions."""
    if entry_mode not in {"next_session_open", "eod_reference"}:
        raise ValueError("entry_mode must be next_session_open or eod_reference")
    decision_at = _aware(signal.get("decision_at"), "decision_at")
    context_at = _aware(signal.get("context_available_at"), "context_available_at")
    if context_at > decision_at:
        raise ValueError("context available_at is after decision_at")
    reference_entry = _finite_decimal(signal.get("entry"), "entry")
    stop = _finite_decimal(signal.get("stop"), "stop")
    target = _finite_decimal(signal.get("target"), "target")
    if reference_entry <= 0 or not 0 < stop < reference_entry < target:
        raise ValueError("invalid entry/stop/target ordering")
    if slippage_bps < 0 or commission < 0:
        raise ValueError("costs must be nonnegative")

    bars = sorted(future_bars, key=lambda row: row["dt"])
    for bar in bars:
        available_at = _aware(bar.get("available_at"), "bar available_at")
        bar_dt = bar.get("dt")
        if not isinstance(bar_dt, date) or available_at.date() > bar_dt:
            raise ValueError("bar available_at is not point-in-time valid for its session")
    if not bars:
        if delisting_return is None:
            return {"status": "excluded_missing_bars", "exit_reason": "missing_bars"}
        value = _finite_decimal(delisting_return, "delisting_return")
        return {
            "status": "included",
            "entry_price": str(_q(reference_entry)),
            "exit_price": str(_q(reference_entry * (Decimal("1") + value))),
            "exit_reason": "delisting",
            "net_return": str(_q(value)),
            "net_r": str(_q(value)),
            "mfe_r": "0.0000",
            "mae_r": str(_q(value)),
            "holding_days": 0,
        }

    entry = reference_entry if entry_mode == "eod_reference" else _finite_decimal(bars[0].get("open"), "open")
    if entry <= 0:
        raise ValueError("entry must be positive")
    risk = entry - stop
    if risk <= 0:
        return {
            "status": "included",
            "entry_price": str(_q(entry)),
            "exit_price": str(_q(entry)),
            "exit_reason": "gap_through_stop",
            "net_return": "0.0000",
            "net_r": "0.0000",
            "mfe_r": "0.0000",
            "mae_r": "0.0000",
            "holding_days": 0,
        }
    max_hold = int(signal.get("max_hold_days", len(bars)))
    selected = bars[:max_hold]
    best_high = entry
    worst_low = entry
    exit_price = _finite_decimal(selected[-1].get("close"), "close")
    exit_reason = "time_exit"
    exit_dt = selected[-1]["dt"]
    first_open = _finite_decimal(selected[0].get("open"), "open")
    if first_open <= stop:
        exit_price = first_open
        exit_reason = "gap_through_stop"
        exit_dt = selected[0]["dt"]
    else:
        for bar in selected:
            high = _finite_decimal(bar.get("high"), "high")
            low = _finite_decimal(bar.get("low"), "low")
            best_high = max(best_high, high)
            worst_low = min(worst_low, low)
            if low <= stop:
                exit_price = stop
                exit_reason = "stop_first_same_bar" if high >= target else "stop"
                exit_dt = bar["dt"]
                break
            if high >= target:
                exit_price = target
                exit_reason = "target"
                exit_dt = bar["dt"]
                break
    slip = slippage_bps / Decimal("10000")
    net_exit = exit_price * (Decimal("1") - slip)
    net_pnl = net_exit - entry - commission
    return {
        "status": "included",
        "entry_price": str(_q(entry)),
        "exit_price": str(_q(exit_price)),
        "exit_reason": exit_reason,
        "net_return": str(_q(net_pnl / entry)),
        "net_r": str(_q(net_pnl / risk)),
        "mfe_r": str(_q((best_high - entry) / risk)),
        "mae_r": str(_q((worst_low - entry) / risk)),
        "holding_days": max(0, (exit_dt - signal["signal_dt"]).days),
    }


def _concentration(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, str]:
    if not rows:
        return {}
    counts = Counter(str(row.get(field, "unknown")) for row in rows)
    total = Decimal(len(rows))
    return {key: str(_q(Decimal(value) / total)) for key, value in sorted(counts.items())}


def _native_metrics(
    rows: Sequence[Mapping[str, Any]],
    all_strategy_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    strategy_id: str,
    confidence_block_days: int,
) -> dict[str, Any]:
    values = [Decimal(str(row["net_r"])) for row in rows]
    returns = [float(row["net_return"]) for row in rows]
    hit_count = sum(row["exit_reason"] == "target" for row in rows)
    stop_count = sum(row["exit_reason"] in {"stop", "stop_first_same_bar", "gap_through_stop"} for row in rows)
    running = Decimal("0")
    peak = Decimal("0")
    worst = Decimal("0")
    for value in values:
        running += value
        peak = max(peak, running)
        worst = min(worst, running - peak)
    avg = Decimal(str(mean([float(value) for value in values]))) if values else Decimal("0")
    if len(values) > 1:
        effective_blocks = max(1, math.ceil(len(values) / confidence_block_days))
        se = Decimal(str(pstdev([float(value) for value in values]) / math.sqrt(effective_blocks)))
    else:
        se = Decimal("0")
    tickers = {str(row["ticker"]) for row in rows}
    overlap = {}
    for other, other_rows in sorted(all_strategy_rows.items()):
        if other == strategy_id:
            continue
        other_tickers = {str(item["ticker"]) for item in other_rows}
        overlap[other] = str(_q(Decimal(len(tickers & other_tickers)) / Decimal(max(1, len(tickers | other_tickers)))))
    return {
        "sample_count": len(rows),
        "hit_rate": str(_q(Decimal(hit_count) / Decimal(max(1, len(rows))))),
        "stop_rate": str(_q(Decimal(stop_count) / Decimal(max(1, len(rows))))),
        "expectancy_r": str(_q(avg)),
        "max_drawdown_r": str(_q(worst)),
        "mfe_r": str(_q(mean([float(row["mfe_r"]) for row in rows]) if rows else 0)),
        "mae_r": str(_q(mean([float(row["mae_r"]) for row in rows]) if rows else 0)),
        "turnover": str(_q(Decimal(len(rows)) / Decimal(max(1, len({row["signal_dt"] for row in rows}))))),
        "median_holding_days": str(_q(median([row["holding_days"] for row in rows]) if rows else 0)),
        "sector_concentration": _concentration(rows, "sector"),
        "regime_concentration": _concentration(rows, "regime"),
        "date_clustered_confidence_interval": [str(_q(avg - Decimal("1.96") * se)), str(_q(avg + Decimal("1.96") * se))],
        "sensitivity": {
            "double_cost_expectancy_return": str(
                _q(mean(returns) - float(DEFAULT_SLIPPAGE_BPS / Decimal("10000")) if returns else 0)
            )
        },
        "overlap": overlap,
    }


def run_multi_strategy_backtest(
    *,
    specs: Sequence[StrategyBacktestSpec],
    signals: Sequence[Mapping[str, Any]],
    bars_by_ticker: Mapping[str, Sequence[Mapping[str, Any]]],
    attempted_parameters: Sequence[Mapping[str, Any]],
    train_size: int,
    test_size: int,
    purge_days: int,
    holdout_size: int,
    confidence_block_days: int = 5,
) -> dict[str, Any]:
    """Run exactly the three setup families with one outcome vocabulary."""
    if confidence_block_days < 1:
        raise ValueError("confidence_block_days must be positive")
    results: dict[str, list[dict[str, Any]]] = {}
    split_reports: dict[str, Any] = {}
    for spec in specs:
        if spec.strategy_id not in _PIVOT_STRATEGIES or spec.strategy_version != 1:
            raise ValueError("unsupported strategy/version")
        if spec.preserve_approval != (spec.strategy_id == "close_confirmed_breakout_v1"):
            raise ValueError("breakout approval parity metadata must be preserved exactly")
        family_signals = [row for row in signals if row.get("strategy_id") == spec.strategy_id]
        dates = sorted({row["signal_dt"] for row in family_signals})
        splits = (
            build_chronological_splits(
                dates,
                mode=spec.split_mode,
                train_size=train_size,
                test_size=test_size,
                purge_days=purge_days,
                holdout_size=min(holdout_size, max(0, len(dates) - 1)),
            )
            if dates
            else ChronologicalSplits(spec.split_mode, (), ())
        )
        split_reports[spec.strategy_id] = {
            "mode": splits.mode,
            "folds": len(splits.folds),
            "purge_days": purge_days,
            "holdout_dates": [item.isoformat() for item in splits.holdout],
        }
        evaluated: list[dict[str, Any]] = []
        for signal in family_signals:
            outcome = evaluate_setup_trade(
                {**signal, "max_hold_days": spec.max_hold_days},
                bars_by_ticker.get(str(signal["ticker"]), ()),
                entry_mode=spec.entry_mode,
            )
            if outcome.get("status") == "included":
                evaluated.append({**signal, **outcome})
        results[spec.strategy_id] = evaluated
    return {
        "strategies": [
            {
                "strategy_id": spec.strategy_id,
                "strategy_version": spec.strategy_version,
                "entry_mode": spec.entry_mode,
                "split": split_reports[spec.strategy_id],
                "approval_metadata_preserved": spec.preserve_approval,
                "metrics": _native_metrics(
                    results[spec.strategy_id], results, spec.strategy_id, confidence_block_days
                ),
            }
            for spec in specs
        ],
        "attempted_parameters": [dict(item) for item in attempted_parameters],
        "holdout_opened_once": True,
        "point_in_time_joins": True,
        "outcome_semantics": "underlying_setup_only",
        "costs": {
            "slippage_bps": str(DEFAULT_SLIPPAGE_BPS),
            "commission_per_trade": str(DEFAULT_COMMISSION_PER_TRADE),
        },
    }


def run_portfolio_allocator_backtest(
    candidates: Sequence[PortfolioBacktestCandidate],
    *,
    starting_equity: Decimal = Decimal("100000"),
    bootstrap_samples: int = 1000,
    block_days: int = 5,
    seed: int = 0,
) -> dict[str, Any]:
    """Expose the chronological policy replay beside setup-native backtests."""
    return run_portfolio_backtest(
        candidates,
        starting_equity=starting_equity,
        bootstrap_samples=bootstrap_samples,
        block_days=block_days,
        seed=seed,
    )


def _json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _dec(value: object, default: Decimal | None = None) -> Decimal:
    if value is None:
        if default is None:
            raise ValueError("missing decimal value")
        return default
    return Decimal(str(value))


def _q(value: float | Decimal, places: str = "0.0001") -> Decimal:
    return Decimal(str(value)).quantize(Decimal(places))


def _sharpe(returns: Sequence[float]) -> Decimal:
    if not returns:
        return Decimal("0")
    avg = mean(returns)
    sd = pstdev(returns)
    if sd == 0:
        if avg > 0:
            return Decimal("999")
        if avg < 0:
            return Decimal("-999")
        return Decimal("0")
    return _q((avg / sd) * math.sqrt(252))


def _cagr(returns: Sequence[float]) -> Decimal:
    if not returns:
        return Decimal("0")
    equity = 1.0
    for ret in returns:
        equity *= 1.0 + ret
    if equity <= 0:
        return Decimal("-1")
    return _q((equity ** (252 / len(returns))) - 1)


def _max_drawdown(returns: Sequence[float]) -> Decimal:
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for ret in returns:
        equity *= 1.0 + ret
        peak = max(peak, equity)
        worst = min(worst, (equity / peak) - 1.0)
    return _q(worst)


def evaluate_underlying_setup_outcome(
    *,
    signal_dt: date,
    entry: Decimal,
    stop: Decimal,
    future_bars: Sequence[dict],
    target_r: Decimal = Decimal("1.5"),
    max_hold_days: int = 10,
    stop_mode: str = "intrabar_low",
) -> dict:
    """Grade whether an underlying technical setup worked after recommendation.

    This grades setup accuracy, not user fill price or option-spread P/L. It uses
    the deterministic recommendation close/stop and looks forward up to the
    strategy horizon. If stop and target both appear inside the same bar, the
    conservative stop-first assumption wins.
    """
    if entry <= 0:
        raise ValueError("entry must be positive")
    risk = entry - stop
    if risk <= 0:
        raise ValueError("stop must be below entry for long setup evaluation")
    target_price = entry + (risk * target_r)
    bars = sorted(future_bars, key=lambda row: row["dt"])[:max_hold_days]
    if not bars:
        return {
            "classification": "no_follow_through",
            "hit_target": False,
            "hit_stop": False,
            "target_price": str(_q(target_price)),
            "mfe_r": "0.0000",
            "mae_r": "0.0000",
            "mfe_pct": "0.0000",
            "mae_pct": "0.0000",
            "days_to_best_move": None,
            "exit_dt": None,
            "exit_reason": "no_future_bars",
        }
    best_high = entry
    worst_low = entry
    best_dt = None
    exit_reason = "time_stop"
    exit_dt = bars[-1]["dt"]
    hit_target = False
    hit_stop = False
    for idx, bar in enumerate(bars, start=1):
        high = _dec(bar.get("high"))
        low = _dec(bar.get("low"))
        close = _dec(bar.get("close"))
        if high > best_high:
            best_high = high
            best_dt = bar["dt"]
        if low < worst_low:
            worst_low = low
        stop_hit = close <= stop if stop_mode == "close_below" else low <= stop
        if stop_hit:
            hit_stop = True
            exit_reason = "stop_or_invalidation"
            exit_dt = bar["dt"]
            break
        if high >= target_price:
            hit_target = True
            exit_reason = "target_1_5r"
            exit_dt = bar["dt"]
            break
    mfe_r = (best_high - entry) / risk
    mae_r = (worst_low - entry) / risk
    mfe_pct = (best_high / entry) - Decimal("1")
    mae_pct = (worst_low / entry) - Decimal("1")
    if hit_target:
        classification = "successful_continuation"
    elif hit_stop:
        classification = "stopped_or_invalidated"
    elif mfe_r >= Decimal("1.0"):
        classification = "partial_success"
    elif best_high > entry:
        classification = "no_follow_through"
    else:
        classification = "failed_breakout"
    return {
        "classification": classification,
        "hit_target": hit_target,
        "hit_stop": hit_stop,
        "target_price": str(_q(target_price)),
        "mfe_r": str(_q(mfe_r)),
        "mae_r": str(_q(mae_r)),
        "mfe_pct": str(_q(mfe_pct)),
        "mae_pct": str(_q(mae_pct)),
        "days_to_best_move": None if best_dt is None else (best_dt - signal_dt).days,
        "exit_dt": exit_dt.isoformat() if hasattr(exit_dt, "isoformat") else str(exit_dt),
        "exit_reason": exit_reason,
    }


def evaluate_setup_outcome_gates(
    outcomes: Sequence[dict],
    *,
    min_sample: int = 100,
    min_oos_sample: int = 25,
    min_hit_rate: Decimal = Decimal("0.55"),
    min_oos_hit_rate: Decimal = Decimal("0.50"),
    max_stop_rate: Decimal = Decimal("0.45"),
    min_median_mfe_r: Decimal = Decimal("1.0"),
    oos_fraction: Decimal = Decimal("0.25"),
) -> dict:
    """Evaluate setup-outcome-native gates for options-timed technical strategies.

    Unlike next-close return backtests, this validates the actual recommendation
    thesis: hit deterministic R target before invalidation within the strategy
    horizon, with a frequency-aware chronological OOS tail.
    """
    ordered = sorted(outcomes, key=lambda row: row["signal_dt"])
    sample = len(ordered)
    oos_size = min(sample, max(min_oos_sample, int((Decimal(sample) * oos_fraction).to_integral_value(rounding="ROUND_CEILING")))) if sample else 0
    oos = ordered[-oos_size:] if oos_size else []

    def _rate(rows: Sequence[dict], key: str) -> Decimal:
        if not rows:
            return Decimal("0")
        return _q(Decimal(sum(1 for row in rows if row.get(key))) / Decimal(len(rows)))

    hit_rate = _rate(ordered, "hit_target")
    oos_hit_rate = _rate(oos, "hit_target")
    stop_rate = _rate(ordered, "hit_stop")
    mfe_values = [_dec(row.get("mfe_r")) for row in ordered]
    median_mfe_r = _q(median(mfe_values)) if mfe_values else Decimal("0")

    failure_reasons: list[str] = []
    if sample < min_sample:
        failure_reasons.append("insufficient_setup_sample")
    if len(oos) < min_oos_sample:
        failure_reasons.append("insufficient_oos_setup_sample")
    if hit_rate < min_hit_rate:
        failure_reasons.append("hit_rate_below_threshold")
    if oos_hit_rate < min_oos_hit_rate:
        failure_reasons.append("oos_hit_rate_below_threshold")
    if stop_rate > max_stop_rate:
        failure_reasons.append("stop_rate_exceeds_threshold")
    if median_mfe_r < min_median_mfe_r:
        failure_reasons.append("median_mfe_r_below_threshold")

    return {
        "passed": not failure_reasons,
        "failure_reasons": failure_reasons,
        "thresholds": {
            "min_sample": min_sample,
            "min_oos_sample": min_oos_sample,
            "min_hit_rate": str(_q(min_hit_rate)),
            "min_oos_hit_rate": str(_q(min_oos_hit_rate)),
            "max_stop_rate": str(_q(max_stop_rate)),
            "min_median_mfe_r": str(_q(min_median_mfe_r)),
            "oos_fraction": str(_q(oos_fraction)),
        },
        "observed": {
            "sample": sample,
            "oos_sample": len(oos),
            "hit_rate": str(hit_rate),
            "oos_hit_rate": str(oos_hit_rate),
            "stop_rate": str(stop_rate),
            "median_mfe_r": str(median_mfe_r),
        },
    }


def evaluate_oos_gates(
    *,
    is_trades: int,
    oos_trades: int,
    oos_sharpe: Decimal,
    max_dd: Decimal,
    min_is_trades: int = DEFAULT_MIN_IS_TRADES,
    min_oos_trades: int = DEFAULT_MIN_OOS_TRADES,
    min_oos_sharpe: Decimal = DEFAULT_MIN_OOS_SHARPE,
    max_oos_drawdown: Decimal = DEFAULT_MAX_OOS_DRAWDOWN,
) -> dict:
    """Evaluate governed OOS promotion gates and return auditable reasons."""
    failure_reasons: list[str] = []
    if is_trades < min_is_trades:
        failure_reasons.append("insufficient_is_trades")
    if oos_trades < min_oos_trades:
        failure_reasons.append("insufficient_oos_trades")
    if oos_sharpe < min_oos_sharpe:
        failure_reasons.append("oos_sharpe_below_threshold")
    if max_dd < -abs(max_oos_drawdown):
        failure_reasons.append("max_drawdown_exceeds_threshold")
    return {
        "survives_oos": len(failure_reasons) == 0,
        "failure_reasons": failure_reasons,
        "thresholds": {
            "min_is_trades": min_is_trades,
            "min_oos_trades": min_oos_trades,
            "min_oos_sharpe": str(min_oos_sharpe),
            "max_oos_drawdown": str(max_oos_drawdown),
        },
        "observed": {
            "is_trades": is_trades,
            "oos_trades": oos_trades,
            "oos_sharpe": str(oos_sharpe),
            "max_dd": str(max_dd),
        },
    }


def ensure_backtest_schema(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS config (
          key text PRIMARY KEY,
          value jsonb NOT NULL,
          updated_at timestamptz DEFAULT now()
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS strategies (
          id serial PRIMARY KEY,
          name text UNIQUE,
          setup_type text,
          status text CHECK (status IN ('research_only','candidate','approved','retired')),
          latest_oos_sharpe numeric,
          latest_oos_verdict boolean,
          last_validated date,
          params jsonb,
          notes text,
          metadata jsonb,
          description text
        )
        """
    )
    conn.execute("ALTER TABLE strategies ADD COLUMN IF NOT EXISTS metadata jsonb")
    conn.execute("ALTER TABLE strategies ADD COLUMN IF NOT EXISTS description text")
    conn.execute("UPDATE strategies SET metadata=COALESCE(metadata, params, '{}'::jsonb) WHERE metadata IS NULL")
    conn.execute("UPDATE strategies SET description=notes WHERE description IS NULL AND notes IS NOT NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_strategies_status ON strategies(status, setup_type)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS backtests (
          id serial PRIMARY KEY,
          strategy_id int REFERENCES strategies(id),
          run_at timestamptz DEFAULT now(),
          window_start date,
          window_end date,
          is_sharpe numeric,
          oos_sharpe numeric,
          oos_cagr numeric,
          max_dd numeric,
          turnover numeric,
          survives_oos boolean,
          params jsonb,
          report jsonb
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_backtests_strategy_run_at ON backtests(strategy_id, run_at DESC)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS research_log (
          id serial PRIMARY KEY,
          ts timestamptz DEFAULT now(),
          hypothesis text,
          rationale text,
          backtest_id int REFERENCES backtests(id),
          outcome text,
          promoted boolean DEFAULT false
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_research_log_ts ON research_log(ts DESC)")
    conn.execute(
        """
        INSERT INTO config(key, value) VALUES
          ('slippage_bps', '{"bps": 10, "direction": "may_only_increase_for_backtests_without_human_review"}'::jsonb),
          ('commission_per_trade', '{"usd": 0, "direction": "may_only_increase_for_backtests_without_human_review"}'::jsonb)
        ON CONFLICT (key) DO NOTHING
        """
    )


def _configured_cost(conn, key: str, numeric_field: str, fallback: Decimal) -> Decimal:
    row = conn.execute("SELECT value FROM config WHERE key=%s", (key,)).fetchone()
    if not row:
        return fallback
    value = row[0]
    if isinstance(value, str):
        value = json.loads(value)
    return _dec(value.get(numeric_field), fallback)


def _validate_costs(conn, *, slippage_bps: Decimal, commission_per_trade: Decimal) -> None:
    configured_slippage = _configured_cost(conn, "slippage_bps", "bps", DEFAULT_SLIPPAGE_BPS)
    configured_commission = _configured_cost(conn, "commission_per_trade", "usd", DEFAULT_COMMISSION_PER_TRADE)
    if slippage_bps < configured_slippage or commission_per_trade < configured_commission:
        raise ValueError(
            "Slippage/cost assumptions may not be reduced to make a result pass; "
            f"requested slippage={slippage_bps}bps commission={commission_per_trade}, "
            f"configured floor slippage={configured_slippage}bps commission={configured_commission}"
        )


def _load_strategy(conn, strategy_name: str) -> tuple[int, str]:
    row = conn.execute("SELECT id, status FROM strategies WHERE name=%s", (strategy_name,)).fetchone()
    if not row:
        raise ValueError(f"strategy not found: {strategy_name}")
    return int(row[0]), str(row[1])


def _load_signal_returns(
    conn,
    *,
    strategy_id: int,
    tickers: Sequence[str],
    window_start: date,
    window_end: date,
    slippage_bps: Decimal,
    commission_per_trade: Decimal,
) -> list[dict]:
    rows = conn.execute(
        """
        WITH ordered_prices AS (
          SELECT ticker, dt, close,
                 lead(dt) OVER (PARTITION BY ticker ORDER BY dt) AS next_dt,
                 lead(close) OVER (PARTITION BY ticker ORDER BY dt) AS next_close
          FROM prices
          WHERE ticker = ANY(%s) AND dt >= %s AND dt <= %s
        )
        SELECT s.ticker, s.dt, p.close, p.next_dt, p.next_close, s.direction
        FROM signals s
        JOIN ordered_prices p ON p.ticker=s.ticker AND p.dt=s.dt
        LEFT JOIN features f ON f.ticker=s.ticker AND f.dt=s.dt
        WHERE s.strategy_id=%s
          AND s.ticker = ANY(%s)
          AND s.dt >= %s AND s.dt < %s
          AND lower(coalesce(s.direction,'')) IN ('long','buy')
          AND p.next_close IS NOT NULL
          AND coalesce(f.liquidity, true) = true
        ORDER BY s.dt, s.ticker
        """,
        ([t.upper() for t in tickers], window_start, window_end, strategy_id, [t.upper() for t in tickers], window_start, window_end),
    ).fetchall()
    cost_rate = float(slippage_bps / Decimal("10000"))
    trades: list[dict] = []
    for ticker, signal_dt, close, next_dt, next_close, direction in rows:
        entry = float(close)
        exit_ = float(next_close)
        gross = (exit_ / entry) - 1.0
        commission_rate = float(commission_per_trade) / entry if entry else 0.0
        net = gross - cost_rate - commission_rate
        trades.append(
            {
                "ticker": ticker,
                "signal_dt": signal_dt,
                "exit_dt": next_dt,
                "direction": direction,
                "entry_close": str(close),
                "exit_close": str(next_close),
                "gross_return": _q(gross),
                "net_return": _q(net),
            }
        )
    return trades


def run_backtest(
    conn,
    *,
    strategy_name: str,
    hypothesis: str,
    rationale: str,
    tickers: Sequence[str],
    window_start: date,
    window_end: date,
    oos_days: int = 63,
    min_oos_sharpe: Decimal = DEFAULT_MIN_OOS_SHARPE,
    min_is_trades: int = DEFAULT_MIN_IS_TRADES,
    min_oos_trades: int = DEFAULT_MIN_OOS_TRADES,
    max_oos_drawdown: Decimal = DEFAULT_MAX_OOS_DRAWDOWN,
    slippage_bps: Decimal = DEFAULT_SLIPPAGE_BPS,
    commission_per_trade: Decimal = DEFAULT_COMMISSION_PER_TRADE,
) -> BacktestResult:
    if oos_days <= 0:
        raise ValueError("oos_days must be positive")
    if not tickers:
        raise ValueError("tickers are required")
    ensure_backtest_schema(conn)
    _validate_costs(conn, slippage_bps=slippage_bps, commission_per_trade=commission_per_trade)
    strategy_id, strategy_status = _load_strategy(conn, strategy_name)
    trades = _load_signal_returns(
        conn,
        strategy_id=strategy_id,
        tickers=tickers,
        window_start=window_start,
        window_end=window_end,
        slippage_bps=slippage_bps,
        commission_per_trade=commission_per_trade,
    )
    unique_exit_dates = sorted({trade["exit_dt"] for trade in trades})
    oos_dates = set(unique_exit_dates[-oos_days:]) if unique_exit_dates else set()
    is_returns = [float(trade["net_return"]) for trade in trades if trade["exit_dt"] not in oos_dates]
    oos_returns = [float(trade["net_return"]) for trade in trades if trade["exit_dt"] in oos_dates]
    is_sharpe = _sharpe(is_returns)
    oos_sharpe = _sharpe(oos_returns)
    oos_cagr = _cagr(oos_returns)
    max_dd = _max_drawdown([float(trade["net_return"]) for trade in trades])
    turnover = _q(Decimal(len(trades)) / Decimal(max(1, len(unique_exit_dates))))
    gate = evaluate_oos_gates(
        is_trades=len(is_returns),
        oos_trades=len(oos_returns),
        oos_sharpe=oos_sharpe,
        max_dd=max_dd,
        min_is_trades=min_is_trades,
        min_oos_trades=min_oos_trades,
        min_oos_sharpe=min_oos_sharpe,
        max_oos_drawdown=max_oos_drawdown,
    )
    survives_oos = bool(gate["survives_oos"])
    params = {
        "tickers": [t.upper() for t in tickers],
        "walk_forward": {
            "oos_days": oos_days,
            "min_oos_sharpe": str(min_oos_sharpe),
            "min_is_trades": min_is_trades,
            "min_oos_trades": min_oos_trades,
            "max_oos_drawdown": str(max_oos_drawdown),
        },
        "costs": {"slippage_bps": str(slippage_bps), "commission_per_trade": str(commission_per_trade)},
    }
    report = {
        "strategy_name": strategy_name,
        "hypothesis": hypothesis,
        "walk_forward": {"is_trades": len(is_returns), "oos_trades": len(oos_returns), "oos_days": oos_days},
        "metrics": {
            "is_sharpe": str(is_sharpe),
            "oos_sharpe": str(oos_sharpe),
            "oos_cagr": str(oos_cagr),
            "max_dd": str(max_dd),
            "turnover": str(turnover),
            "survives_oos": survives_oos,
        },
        "gate": gate,
        "costs": params["costs"],
        "sample_trades": trades[:20],
    }
    backtest_id = conn.execute(
        """
        INSERT INTO backtests(strategy_id, window_start, window_end, is_sharpe, oos_sharpe, oos_cagr, max_dd, turnover, survives_oos, params, report)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
        RETURNING id
        """,
        (strategy_id, window_start, window_end, is_sharpe, oos_sharpe, oos_cagr, max_dd, turnover, survives_oos, _json(params), _json(report)),
    ).fetchone()[0]
    promoted = survives_oos and strategy_status in {"research_only", "candidate"}
    outcome = "survived_oos_candidate" if survives_oos else "failed_oos_research_only"
    conn.execute(
        """
        INSERT INTO research_log(hypothesis, rationale, backtest_id, outcome, promoted)
        VALUES (%s,%s,%s,%s,%s)
        """,
        (hypothesis, rationale, backtest_id, outcome, promoted),
    )
    if survives_oos:
        conn.execute(
            """
            UPDATE strategies
            SET status = CASE WHEN status='research_only' THEN 'candidate' ELSE status END,
                latest_oos_sharpe=%s,
                latest_oos_verdict=%s,
                last_validated=%s,
                notes=concat_ws(E'\n', notes, %s::text)
            WHERE id=%s
            """,
            (oos_sharpe, survives_oos, window_end, f"Walk-forward OOS survived on {window_end}; eligible for candidate only, never auto-approved.", strategy_id),
        )
    else:
        conn.execute(
            """
            UPDATE strategies
            SET latest_oos_sharpe=%s,
                latest_oos_verdict=%s,
                last_validated=%s
            WHERE id=%s
            """,
            (oos_sharpe, survives_oos, window_end, strategy_id),
        )
    return BacktestResult(
        backtest_id=int(backtest_id),
        strategy_id=strategy_id,
        strategy_name=strategy_name,
        is_sharpe=is_sharpe,
        oos_sharpe=oos_sharpe,
        oos_cagr=oos_cagr,
        max_dd=max_dd,
        turnover=turnover,
        survives_oos=survives_oos,
        trades=len(trades),
        oos_trades=len(oos_returns),
    )


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wolfy EOD walk-forward backtest runner")
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    parser.add_argument("--strategy-name", required=True)
    parser.add_argument("--hypothesis", required=True)
    parser.add_argument("--rationale", default="")
    parser.add_argument("--tickers", required=True, help="Comma-separated tickers")
    parser.add_argument("--window-start", required=True)
    parser.add_argument("--window-end", required=True)
    parser.add_argument("--oos-days", type=int, default=63)
    parser.add_argument("--min-oos-sharpe", default=str(DEFAULT_MIN_OOS_SHARPE))
    parser.add_argument("--slippage-bps", default=str(DEFAULT_SLIPPAGE_BPS))
    parser.add_argument("--commission-per-trade", default=str(DEFAULT_COMMISSION_PER_TRADE))
    args = parser.parse_args(argv)
    import psycopg

    with psycopg.connect(args.dsn) as conn:
        result = run_backtest(
            conn,
            strategy_name=args.strategy_name,
            hypothesis=args.hypothesis,
            rationale=args.rationale,
            tickers=[ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()],
            window_start=_parse_date(args.window_start),
            window_end=_parse_date(args.window_end),
            oos_days=args.oos_days,
            min_oos_sharpe=Decimal(args.min_oos_sharpe),
            slippage_bps=Decimal(args.slippage_bps),
            commission_per_trade=Decimal(args.commission_per_trade),
        )
    print(json.dumps(result.__dict__, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
