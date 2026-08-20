#!/usr/bin/env python3
"""Hermes-EOD monitoring and approved-strategy revalidation loop.

This module is intentionally conservative:
- It never promotes a strategy without prior paper-only approval metadata.
- It may reactivate a previously approved paper strategy only when the same
  deterministic setup-outcome gate passes and auto-reactivation was authorized.
- It never executes trades.
- It only flags/rejects setup or position rows when deterministic database facts
  show an invalidation breach or near-term event landmine.
- It revalidates governed paper strategies before demoting stale or failed
  approved strategies back to candidate.
"""
from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Sequence

import psycopg

from eod_backtest import evaluate_setup_outcome_gates, evaluate_underlying_setup_outcome

DEFAULT_DSN = os.environ.get("WOLFY_POSTGRES_DSN", "dbname=wolfy user=root host=/var/run/postgresql")
DEFAULT_STALE_AFTER_DAYS = int(os.environ.get("WOLFY_STRATEGY_STALE_AFTER_DAYS", "31"))
SETUP_GATE_DEFINITION_VERSION = 1
_REQUIRED_SETUP_GATE_THRESHOLDS = {
    "min_sample",
    "min_oos_sample",
    "min_hit_rate",
    "min_oos_hit_rate",
    "max_stop_rate",
    "min_median_mfe_r",
    "oos_fraction",
}
_CONSERVATIVE_SETUP_GATE_THRESHOLDS = {
    "min_sample": 100,
    "min_oos_sample": 25,
    "min_hit_rate": "0.55",
    "min_oos_hit_rate": "0.50",
    "max_stop_rate": "0.45",
    "min_median_mfe_r": "1.0",
    "oos_fraction": "0.25",
}


def _parse_gate_count(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.isdigit():
        parsed = int(value)
        if value != str(parsed):
            return None
    else:
        return None
    return parsed if parsed >= 1 else None


def _normalize_approved_setup_gate(gate: Any) -> dict[str, Any] | None:
    """Return the complete immutable gate definition, or fail closed."""
    if not isinstance(gate, Mapping):
        return None
    raw_obj = gate.get("thresholds")
    if not isinstance(raw_obj, Mapping):
        return None
    raw = dict(raw_obj)
    validation_mode = gate.get("validation_mode")
    definition_version = gate.get("gate_definition_version")
    if validation_mode != "underlying_setup_outcome_revalidation":
        return None
    if type(definition_version) is not int or definition_version != SETUP_GATE_DEFINITION_VERSION:
        return None
    if gate.get("passed") is not True or set(raw) != _REQUIRED_SETUP_GATE_THRESHOLDS:
        return None
    try:
        min_sample = _parse_gate_count(raw["min_sample"])
        min_oos_sample = _parse_gate_count(raw["min_oos_sample"])
        min_hit_rate = Decimal(str(raw["min_hit_rate"]))
        min_oos_hit_rate = Decimal(str(raw["min_oos_hit_rate"]))
        max_stop_rate = Decimal(str(raw["max_stop_rate"]))
        min_median_mfe_r = Decimal(str(raw["min_median_mfe_r"]))
        oos_fraction = Decimal(str(raw["oos_fraction"]))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if min_sample is None or min_oos_sample is None:
        return None
    decimal_values = (min_hit_rate, min_oos_hit_rate, max_stop_rate, min_median_mfe_r, oos_fraction)
    if not all(value.is_finite() for value in decimal_values):
        return None
    if (
        min_sample < 1
        or min_oos_sample < 1
        or min_oos_sample > min_sample
        or not 0 <= min_hit_rate <= 1
        or not 0 <= min_oos_hit_rate <= 1
        or not 0 <= max_stop_rate <= 1
        or min_median_mfe_r < 0
        or not 0 < oos_fraction <= 1
    ):
        return None
    return {
        "passed": True,
        "validation_mode": "underlying_setup_outcome_revalidation",
        "gate_definition_version": SETUP_GATE_DEFINITION_VERSION,
        "thresholds": {
            "min_sample": min_sample,
            "min_oos_sample": min_oos_sample,
            "min_hit_rate": str(min_hit_rate),
            "min_oos_hit_rate": str(min_oos_hit_rate),
            "max_stop_rate": str(max_stop_rate),
            "min_median_mfe_r": str(min_median_mfe_r),
            "oos_fraction": str(oos_fraction),
        },
    }


def _configured_signal_value(raw: dict[str, Any], metadata: dict[str, Any], key: str, default: Any) -> Any:
    if key in raw:
        return raw[key]
    if key in metadata:
        return metadata[key]
    return default


def _parse_target_r(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not parsed.is_finite() or parsed <= 0 or parsed > 10:
        return None
    return parsed


def _parse_max_hold_days(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.isdigit():
        parsed = int(value)
        if value != str(parsed):
            return None
    else:
        return None
    return parsed if 1 <= parsed <= 60 else None


def _parse_stop_mode(value: Any) -> str | None:
    if value in (None, "", "intrabar_low"):
        return "intrabar_low"
    if value == "close_below_breakout_level":
        return "close_below"
    return None


def _approved_gate_passed(gate: dict[str, Any], approved_definition: dict[str, Any] | None) -> bool:
    return approved_definition is not None and gate.get("passed") is True


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def ensure_monitoring_schema(conn) -> None:
    """Create the non-destructive tables/indexes needed by monitoring."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS eod_monitoring_events (
          id serial PRIMARY KEY,
          run_at timestamptz NOT NULL DEFAULT now(),
          as_of date NOT NULL,
          object_type text NOT NULL,
          object_id int NOT NULL,
          ticker text,
          action text NOT NULL,
          reason text NOT NULL,
          detail jsonb NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_eod_monitoring_events_as_of ON eod_monitoring_events(as_of, object_type, ticker)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS research_log (
          id serial PRIMARY KEY,
          ts timestamptz DEFAULT now(),
          hypothesis text,
          rationale text,
          backtest_id int,
          outcome text,
          promoted boolean DEFAULT false
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_research_log_ts ON research_log(ts DESC)")


def _latest_close(conn, ticker: str, as_of: date) -> tuple[date, Decimal] | None:
    row = conn.execute(
        """
        SELECT dt, close
        FROM prices
        WHERE ticker=%s AND dt <= %s AND close IS NOT NULL
        ORDER BY dt DESC
        LIMIT 1
        """,
        (ticker, as_of),
    ).fetchone()
    if not row:
        return None
    return row[0], Decimal(str(row[1]))


def _event_landmines(conn, ticker: str, as_of: date, horizon_days: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT event_dt, session, confirmed
        FROM earnings_calendar
        WHERE ticker=%s AND event_dt >= %s AND event_dt <= %s
        ORDER BY event_dt
        """,
        (ticker, as_of, as_of + timedelta(days=horizon_days)),
    ).fetchall()
    return [
        {"event_dt": row[0], "session": row[1], "confirmed": row[2]}
        for row in rows
    ]


def _risk_reasons(conn, *, ticker: str, as_of: date, invalidation: Any, event_horizon_days: int) -> tuple[list[str], dict[str, Any]]:
    reasons: list[str] = []
    detail: dict[str, Any] = {"ticker": ticker, "as_of": as_of}
    close_row = _latest_close(conn, ticker, as_of)
    if close_row:
        close_dt, close = close_row
        detail["latest_close"] = str(close)
        detail["latest_close_dt"] = close_dt
        if invalidation is not None and close <= Decimal(str(invalidation)):
            reasons.append(f"invalidation breach: close {close} <= invalidation {invalidation}")
    else:
        detail["latest_close"] = None
    events = _event_landmines(conn, ticker, as_of, event_horizon_days)
    if events:
        reasons.append("earnings/event landmine inside pre-open horizon")
        detail["events"] = events
    return reasons, detail


def _record_monitor_event(
    conn,
    *,
    as_of: date,
    object_type: str,
    object_id: int,
    ticker: str,
    action: str,
    reasons: list[str],
    detail: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO eod_monitoring_events(as_of, object_type, object_id, ticker, action, reason, detail)
        VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)
        """,
        (as_of, object_type, object_id, ticker, action, "; ".join(reasons), _json(detail)),
    )


def run_preopen_monitoring(conn, *, as_of: date | None = None, event_horizon_days: int = 1) -> dict[str, Any]:
    """Flag last-night setups and open positions for deterministic risk changes."""
    ensure_monitoring_schema(conn)
    as_of = as_of or date.today()
    setups_flagged = 0
    positions_flagged = 0

    setup_rows = conn.execute(
        """
        SELECT id, ticker, invalidation
        FROM setups
        WHERE for_session <= %s
          AND status IN ('proposed','pending_review')
        """,
        (as_of,),
    ).fetchall()
    for setup_id, ticker, invalidation in setup_rows:
        reasons, detail = _risk_reasons(conn, ticker=ticker, as_of=as_of, invalidation=invalidation, event_horizon_days=event_horizon_days)
        if not reasons:
            continue
        conn.execute("UPDATE setups SET status='rejected' WHERE id=%s", (setup_id,))
        _record_monitor_event(conn, as_of=as_of, object_type="setup", object_id=setup_id, ticker=ticker, action="rejected", reasons=reasons, detail=detail)
        setups_flagged += 1

    position_rows = conn.execute(
        """
        SELECT id, ticker, invalidation
        FROM positions
        WHERE lower(coalesce(status,'')) IN ('open','taken','active')
        """
    ).fetchall()
    for position_id, ticker, invalidation in position_rows:
        reasons, detail = _risk_reasons(conn, ticker=ticker, as_of=as_of, invalidation=invalidation, event_horizon_days=event_horizon_days)
        if not reasons:
            continue
        conn.execute("UPDATE positions SET status='flagged' WHERE id=%s", (position_id,))
        _record_monitor_event(conn, as_of=as_of, object_type="position", object_id=position_id, ticker=ticker, action="flagged", reasons=reasons, detail=detail)
        positions_flagged += 1

    return {
        "as_of": str(as_of),
        "setups_checked": len(setup_rows),
        "positions_checked": len(position_rows),
        "setups_flagged": setups_flagged,
        "positions_flagged": positions_flagged,
    }


def run_setup_outcome_strategy_revalidation(
    conn,
    *,
    strategy_name: str,
    as_of: date | None = None,
    validation_run_date: date | None = None,
) -> dict[str, Any]:
    """Recompute a paper strategy's stored setup-outcome gate and safely reactivate it."""
    ensure_monitoring_schema(conn)
    as_of = as_of or date.today()
    validation_run_date = validation_run_date or date.today()
    row = conn.execute(
        "SELECT id,status,metadata FROM strategies WHERE name=%s",
        (strategy_name,),
    ).fetchone()
    if not row:
        raise ValueError(f"unknown strategy: {strategy_name}")
    strategy_id, status, metadata_obj = row
    metadata = dict(metadata_obj) if isinstance(metadata_obj, Mapping) else {}
    approved_gate_obj = metadata.get("approved_setup_outcome_gate")
    approved_gate_source = dict(approved_gate_obj) if isinstance(approved_gate_obj, Mapping) else {}
    approved_gate_definition = _normalize_approved_setup_gate(approved_gate_source)
    approved_gate = approved_gate_definition or approved_gate_source
    thresholds = dict(
        approved_gate_definition["thresholds"]
        if approved_gate_definition is not None
        else _CONSERVATIVE_SETUP_GATE_THRESHOLDS
    )
    signal_rows = conn.execute(
        """
        SELECT dt,ticker,raw
        FROM signals
        WHERE strategy_id=%s AND direction IN ('long','buy') AND dt <= %s
        ORDER BY dt,ticker
        """,
        (strategy_id, as_of),
    ).fetchall()
    signal_tickers = sorted({str(row[1]) for row in signal_rows})
    latest_bar_row = conn.execute(
        "SELECT max(dt) FROM prices WHERE ticker = ANY(%s) AND dt <= %s",
        (signal_tickers, as_of),
    ).fetchone() if signal_tickers else None
    data_through = latest_bar_row[0] if latest_bar_row and latest_bar_row[0] is not None else as_of
    outcomes: list[dict[str, Any]] = []
    for signal_dt, ticker, raw_obj in signal_rows:
        if not isinstance(raw_obj, Mapping):
            continue
        raw = dict(raw_obj)
        entry_value = raw["close"] if "close" in raw else 0
        if "invalidation" in raw:
            stop_value = raw["invalidation"]
        elif "prior_5d_high" in raw:
            stop_value = raw["prior_5d_high"]
        else:
            stop_value = 0
        target_value = _configured_signal_value(raw, metadata, "target_r", "1.0")
        max_hold_value = _configured_signal_value(raw, metadata, "max_hold_days", 10)
        try:
            entry = Decimal(str(entry_value))
            stop = Decimal(str(stop_value))
        except (InvalidOperation, TypeError, ValueError):
            continue
        target_r = _parse_target_r(target_value)
        max_hold_days = _parse_max_hold_days(max_hold_value)
        if (
            not entry.is_finite()
            or not stop.is_finite()
            or entry <= 0
            or stop <= 0
            or stop >= entry
            or target_r is None
            or max_hold_days is None
        ):
            continue
        future_rows = conn.execute(
            """
            SELECT dt,high,low,close
            FROM prices
            WHERE ticker=%s AND dt > %s AND dt <= %s
              AND high IS NOT NULL AND low IS NOT NULL AND close IS NOT NULL
            ORDER BY dt
            LIMIT %s
            """,
            (ticker, signal_dt, data_through, max_hold_days),
        ).fetchall()
        future_bars = [
            {"dt": bar[0], "high": bar[1], "low": bar[2], "close": bar[3]}
            for bar in future_rows
        ]
        stop_rule_value = _configured_signal_value(raw, metadata, "stop_rule", "")
        stop_mode = _parse_stop_mode(stop_rule_value)
        if stop_mode is None:
            continue
        outcome = evaluate_underlying_setup_outcome(
            signal_dt=signal_dt,
            entry=entry,
            stop=stop,
            future_bars=future_bars,
            target_r=target_r,
            max_hold_days=max_hold_days,
            stop_mode=stop_mode,
        )
        if not outcome["hit_target"] and not outcome["hit_stop"] and len(future_bars) < max_hold_days:
            continue
        outcomes.append({**outcome, "signal_dt": signal_dt, "ticker": ticker})

    gate = evaluate_setup_outcome_gates(
        outcomes,
        min_sample=int(thresholds.get("min_sample", 100)),
        min_oos_sample=int(thresholds.get("min_oos_sample", 25)),
        min_hit_rate=Decimal(str(thresholds.get("min_hit_rate", "0.55"))),
        min_oos_hit_rate=Decimal(str(thresholds.get("min_oos_hit_rate", "0.50"))),
        max_stop_rate=Decimal(str(thresholds.get("max_stop_rate", "0.45"))),
        min_median_mfe_r=Decimal(str(thresholds.get("min_median_mfe_r", "1.0"))),
        oos_fraction=Decimal(str(thresholds.get("oos_fraction", "0.25"))),
    )
    passed = _approved_gate_passed(gate, approved_gate_definition)
    gate = {
        **gate,
        "passed": passed,
        "validation_mode": "underlying_setup_outcome_revalidation",
        "gate_definition_version": SETUP_GATE_DEFINITION_VERSION,
        "approved_gate_definition_valid": approved_gate_definition is not None,
    }
    authorized = (
        metadata.get("paper_recommendation_approval") is True
        and metadata.get("approval_scope") == "paper_only_no_live_execution"
        and metadata.get("future_same_gate_auto_activation_allowed") is True
        and approved_gate_definition is not None
    )
    reactivated = passed and authorized and status == "candidate"
    serializable_outcomes = [
        {**item, "signal_dt": item["signal_dt"].isoformat()}
        for item in outcomes
    ]
    report = {
        "strategy": strategy_name,
        "validation_mode": "underlying_setup_outcome_revalidation",
        "validated_through": data_through.isoformat(),
        "validation_run_date": validation_run_date.isoformat(),
        "gate": gate,
        "sample_outcomes": serializable_outcomes[:20],
    }
    signal_dates = [item["signal_dt"] for item in outcomes]
    backtest_id = conn.execute(
        """
        INSERT INTO backtests(strategy_id,window_start,window_end,is_sharpe,oos_sharpe,survives_oos,params,report)
        VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
        RETURNING id
        """,
        (
            strategy_id,
            min(signal_dates) if signal_dates else None,
            max(signal_dates) if signal_dates else as_of,
            gate["observed"]["hit_rate"],
            gate["observed"]["oos_hit_rate"],
            passed,
            _json(gate["thresholds"]),
            _json(report),
        ),
    ).fetchone()[0]
    updated_metadata = {
        **metadata,
        "approved_setup_outcome_gate": approved_gate,
        "latest_setup_outcome_gate": gate,
        "latest_setup_outcome_backtest_id": int(backtest_id),
        "validated_through": data_through.isoformat(),
        "validation_run_date": validation_run_date.isoformat(),
    }
    next_status = "approved" if reactivated or (passed and status == "approved") else status
    conn.execute(
        """
        UPDATE strategies
        SET status=%s, latest_oos_sharpe=%s, latest_oos_verdict=%s,
            last_validated=%s, metadata=%s::jsonb,
            notes=concat_ws(E'\n',notes,%s::text)
        WHERE id=%s
        """,
        (
            next_status,
            gate["observed"]["oos_hit_rate"],
            passed,
            validation_run_date,
            _json(updated_metadata),
            f"Setup-outcome revalidated on {validation_run_date} through {data_through}: passed={passed}; reactivated={reactivated}.",
            strategy_id,
        ),
    )
    conn.execute(
        """
        INSERT INTO research_log(hypothesis,rationale,backtest_id,outcome,promoted)
        VALUES (%s,%s,%s,%s,%s)
        """,
        (
            f"setup outcome revalidation:{strategy_name}",
            _json({"gate": gate, "authorized": authorized, "validated_through": data_through}),
            backtest_id,
            "passed_reactivated" if reactivated else ("passed" if passed else "failed"),
            reactivated,
        ),
    )
    return {
        "strategy_id": strategy_id,
        "strategy_name": strategy_name,
        "backtest_id": int(backtest_id),
        "passed": passed,
        "authorized": authorized,
        "reactivated": reactivated,
        "status": next_status,
        "validated_through": data_through.isoformat(),
        "validation_run_date": validation_run_date.isoformat(),
        "gate": gate,
    }


def run_monthly_strategy_revalidation(
    conn,
    *,
    as_of: date | None = None,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    strategy_names: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Freshly revalidate authorized paper strategies, then demote stale/failed approvals."""
    ensure_monitoring_schema(conn)
    as_of = as_of or date.today()
    cutoff = as_of - timedelta(days=stale_after_days)
    scope_clause = " AND name = ANY(%s)" if strategy_names is not None else ""
    scope_params: tuple[Any, ...] = ([str(name) for name in strategy_names],) if strategy_names is not None else ()
    refresh_rows = conn.execute(
        f"""
        SELECT name
        FROM strategies
        WHERE status IN ('approved','candidate')
          AND metadata->'paper_recommendation_approval'='true'::jsonb
          AND metadata->>'approval_scope'='paper_only_no_live_execution'
          AND metadata->'future_same_gate_auto_activation_allowed'='true'::jsonb
          AND (
            status='approved'
            OR (
              metadata->'approved_setup_outcome_gate'->'passed'='true'::jsonb
              AND metadata->'approved_setup_outcome_gate'->>'validation_mode'='underlying_setup_outcome_revalidation'
              AND metadata->'approved_setup_outcome_gate'->'gate_definition_version'='1'::jsonb
              AND (metadata->'approved_setup_outcome_gate'->'thresholds') ?& ARRAY[
                'min_sample','min_oos_sample','min_hit_rate','min_oos_hit_rate',
                'max_stop_rate','min_median_mfe_r','oos_fraction'
              ]
            )
          )
          {scope_clause}
        ORDER BY id
        """,
        scope_params,
    ).fetchall()
    revalidations: list[dict[str, Any]] = []
    for (strategy_name,) in refresh_rows:
        revalidations.append(
            run_setup_outcome_strategy_revalidation(
                conn,
                strategy_name=strategy_name,
                as_of=as_of,
                validation_run_date=as_of,
            )
        )
    rows = conn.execute(
        f"""
        SELECT id, name, latest_oos_verdict, last_validated, notes
        FROM strategies
        WHERE status='approved'
          AND (last_validated IS NULL OR last_validated < %s OR coalesce(latest_oos_verdict, false) = false)
          {scope_clause}
        ORDER BY id
        """,
        (cutoff, *scope_params),
    ).fetchall()
    demoted: list[dict[str, Any]] = []
    for strategy_id, name, latest_oos_verdict, last_validated, notes in rows:
        reasons: list[str] = []
        if last_validated is None:
            reasons.append("missing monthly validation date")
        elif last_validated < cutoff:
            reasons.append(f"validation stale: last_validated {last_validated} < cutoff {cutoff}")
        if latest_oos_verdict is False or latest_oos_verdict is None:
            reasons.append(f"latest OOS verdict not passing: {latest_oos_verdict}")
        reason_text = "; ".join(reasons)
        conn.execute(
            """
            UPDATE strategies
            SET status='candidate',
                notes=coalesce(notes,'') || %s::text
            WHERE id=%s
            """,
            (f"\n[{as_of}] Demoted by EOD monitoring: {reason_text}", strategy_id),
        )
        conn.execute(
            """
            INSERT INTO research_log(hypothesis, rationale, backtest_id, outcome, promoted)
            VALUES (%s,%s,NULL,'demoted_to_candidate',false)
            """,
            (f"monthly revalidation:{name}", reason_text),
        )
        demoted.append({"strategy_id": strategy_id, "name": name, "reason": reason_text, "previous_notes": notes})
    return {
        "as_of": str(as_of),
        "cutoff": str(cutoff),
        "strategies_revalidated": len(revalidations),
        "strategies_reactivated": sum(1 for item in revalidations if item["reactivated"]),
        "revalidations": revalidations,
        "strategies_checked": len(rows),
        "strategies_demoted": len(demoted),
        "demoted": demoted,
    }


def run_monitoring_cycle(conn, *, as_of: date | None = None, stale_after_days: int = DEFAULT_STALE_AFTER_DAYS) -> dict[str, Any]:
    as_of = as_of or date.today()
    preopen = run_preopen_monitoring(conn, as_of=as_of)
    revalidation = run_monthly_strategy_revalidation(conn, as_of=as_of, stale_after_days=stale_after_days)
    return {"preopen": preopen, "monthly_revalidation": revalidation}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Wolfy EOD monitoring/revalidation checks")
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    parser.add_argument("--as-of", default=None, help="YYYY-MM-DD; defaults to today")
    parser.add_argument("--stale-after-days", type=int, default=DEFAULT_STALE_AFTER_DAYS)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    with psycopg.connect(args.dsn) as conn:
        result = run_monitoring_cycle(conn, as_of=as_of, stale_after_days=args.stale_after_days)
    actionable = result["preopen"]["setups_flagged"] + result["preopen"]["positions_flagged"] + result["monthly_revalidation"]["strategies_demoted"]
    if args.json or actionable:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
