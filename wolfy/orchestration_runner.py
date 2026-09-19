#!/usr/bin/env python3
"""Shared runners for Wolfy's cron-facing orchestration wrappers.

The public wrappers in /root/.hermes/scripts are kept stable for Hermes cron,
while this module owns common subprocess construction, dry-run behavior, and
EOD date/session handling.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from typing import Sequence

from orchestration_config import (
    CORE_EOD_UNIVERSE,
    DEFAULT_EOD_LOOKBACK_DAYS,
    DEFAULT_EOD_SOURCE,
    DRY_RUN_EOD_UNIVERSE,
    EOD_INGEST_SHARDS,
    WOLFY_DIR,
    parse_tickers,
    tickers_csv,
)


def eod_price_features_command(
    *,
    tickers: Sequence[str],
    source: str = DEFAULT_EOD_SOURCE,
    days: int = DEFAULT_EOD_LOOKBACK_DAYS,
    no_validate: bool = False,
    refresh_universe: bool = False,
    eodhs_fallback_max_tickers: int = 0,
) -> list[str]:
    """Build the eod_price_features.py command used by ingest wrappers."""
    cmd = [
        sys.executable,
        str(WOLFY_DIR / "eod_price_features.py"),
        "--source",
        source,
        "--tickers",
        tickers_csv(list(tickers)),
        "--days",
        str(days),
    ]
    if no_validate:
        cmd.append("--no-validate")
    if refresh_universe:
        cmd.append("--refresh-universe")
    if eodhs_fallback_max_tickers:
        cmd.extend(["--eodhs-fallback-max-tickers", str(eodhs_fallback_max_tickers)])
    return cmd


def run_eod_ingest(
    *,
    tickers: Sequence[str] | None = None,
    source: str = DEFAULT_EOD_SOURCE,
    days: int = DEFAULT_EOD_LOOKBACK_DAYS,
    dry_run: bool = False,
    refresh_universe: bool = False,
    eodhs_fallback_max_tickers: int = 0,
) -> int:
    """Run EOD price/feature ingest or a no-write fetch/feature smoke."""
    selected = list(tickers or (DRY_RUN_EOD_UNIVERSE if dry_run else CORE_EOD_UNIVERSE))

    if dry_run:
        from datetime import timedelta
        from eod_price_features import (
            _default_massive_eod_end_dt,
            compute_feature_rows,
            fetch_eodhs_eod_bars,
            fetch_massive_eod_bars,
            fetch_yahoo_chart_bars,
        )

        end_dt = _default_massive_eod_end_dt()
        if source == "massive":
            bars = fetch_massive_eod_bars(
                selected,
                start_dt=end_dt - timedelta(days=min(days, 30)),
                end_dt=end_dt,
            )
            source_label = "massive-adjusted-eod"
        elif source == "eodhs":
            bars = fetch_eodhs_eod_bars(
                selected,
                start_dt=end_dt - timedelta(days=min(days, 10)),
                end_dt=end_dt,
                max_tickers=min(len(selected), 3),
            )
            source_label = "eodhs-eod-fallback"
        else:
            bars = fetch_yahoo_chart_bars(selected, days=min(days, 30))
            source_label = "yahoo-chart-delayed"
        rows = compute_feature_rows(bars)
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "writes": False,
                    "source": source_label,
                    "tickers": selected,
                    "bars_fetched": len(bars),
                    "feature_rows_computed": len(rows),
                    "latest_dates": {
                        ticker: max((str(bar.dt) for bar in bars if bar.ticker == ticker), default=None)
                        for ticker in selected
                    },
                },
                sort_keys=True,
            )
        )
        return 0

    return subprocess.call(
        eod_price_features_command(
            tickers=selected,
            source=source,
            days=days,
            refresh_universe=refresh_universe,
            eodhs_fallback_max_tickers=eodhs_fallback_max_tickers,
        )
    )


def run_eod_ingest_shard(shard_id: int) -> int:
    """Run one bounded after-close ingest shard by configured shard id."""
    if shard_id not in EOD_INGEST_SHARDS:
        raise ValueError(f"unknown EOD ingest shard_id={shard_id}; expected one of {sorted(EOD_INGEST_SHARDS)}")
    return subprocess.call(
        eod_price_features_command(
            tickers=EOD_INGEST_SHARDS[shard_id],
            source=DEFAULT_EOD_SOURCE,
            days=DEFAULT_EOD_LOOKBACK_DAYS,
            no_validate=True,
        )
    )


def next_business_day(day: dt.date) -> dt.date:
    """Compatibility wrapper returning the next actual NYSE session."""
    from eod_readiness import next_nyse_session

    return next_nyse_session(day)


def latest_price_date(conn, tickers: list[str]) -> dt.date:
    row = conn.execute("SELECT max(dt) FROM prices WHERE ticker = ANY(%s)", (tickers,)).fetchone()
    if not row or row[0] is None:
        raise RuntimeError("no EOD prices available for signal generation")
    return row[0]


def evaluate_current_eod_readiness(
    conn,
    *,
    tickers: Sequence[str],
    decision_at: dt.datetime | None = None,
):
    """Gate the current run on its exact point-in-time pivot snapshot."""
    from eod_readiness import NY, SourceMode, evaluate_eod_readiness

    del tickers  # Snapshot membership is authoritative; CLI symbols cannot widen it.
    gate_time = decision_at or dt.datetime.now(NY)
    return evaluate_eod_readiness(
        conn,
        as_of=gate_time,
        universe=(),
        source_mode=SourceMode.FREE_T_PLUS_1,
        decision_at=gate_time,
        require_universe_snapshot=True,
    )


def evaluate_replay_eod_readiness(
    conn,
    *,
    tickers: Sequence[str],
    signal_dt: dt.date,
    decision_at: dt.datetime | None = None,
):
    """Gate a replay on an immutable snapshot for the exact historical date."""
    from eod_readiness import NY, SourceMode, evaluate_eod_readiness

    del tickers  # Replay symbols cannot substitute for historical snapshot evidence.
    gate_time = decision_at or dt.datetime.now(NY)
    return evaluate_eod_readiness(
        conn,
        as_of=gate_time,
        universe=(),
        source_mode=SourceMode.FREE_T_PLUS_1,
        provider_availability_verified=False,
        expected_session=signal_dt,
        decision_at=gate_time,
        require_universe_snapshot=True,
    )


def eod_readiness_payload(readiness) -> dict:
    """Return stable JSON-safe diagnostics for the readiness decision."""
    return {
        "expected_session": readiness.expected_session.isoformat(),
        "latest_complete_session": (
            readiness.latest_complete_session.isoformat()
            if readiness.latest_complete_session is not None
            else None
        ),
        "coverage_numerator": readiness.coverage_numerator,
        "coverage_denominator": readiness.coverage_denominator,
        "missing_symbols": list(readiness.missing_symbols),
        "source_mode": readiness.source_mode.value,
        "publishable": readiness.publishable,
        "universe_snapshot_id": readiness.universe_snapshot_id,
        "universe_policy_version": readiness.universe_policy_version,
        "universe_source_fingerprint": readiness.universe_source_fingerprint,
        "benchmark_coverage_numerator": readiness.benchmark_coverage_numerator,
        "benchmark_coverage_denominator": readiness.benchmark_coverage_denominator,
        "member_coverage_numerator": readiness.member_coverage_numerator,
        "member_coverage_denominator": readiness.member_coverage_denominator,
        "incomplete_reasons": list(readiness.incomplete_reasons),
    }


def load_mid_small_portfolio_candidates(conn, run_id) -> tuple[object, ...]:
    """Read immutable common-contract candidates for one daily run."""
    import uuid

    from portfolio_allocator import PortfolioCandidate

    try:
        canonical_run_id = uuid.UUID(str(run_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("run_id must be a UUID") from exc
    rows = conn.execute(
        """SELECT candidate_id,universe_snapshot_id,ticker,strategy_id,
                  strategy_version,sector,score,entry,stop,target
             FROM setup_candidates
            WHERE run_id=%s
            ORDER BY score DESC,ticker,strategy_id""",
        (canonical_run_id,),
    ).fetchall()
    return tuple(
        PortfolioCandidate(
            candidate_id=uuid.UUID(str(row[0])),
            universe_snapshot_id=uuid.UUID(str(row[1])),
            ticker=row[2],
            strategy_id=row[3],
            strategy_version=row[4],
            sector=row[5],
            score=row[6],
            entry=row[7],
            stop=row[8],
            target=row[9],
        )
        for row in rows
    )


def load_mid_small_existing_positions(conn) -> tuple[object, ...]:
    """Read active paper positions for pure pre-allocation capacity accounting."""
    from decimal import Decimal, InvalidOperation

    from portfolio_allocator import ExistingPosition

    rows = conn.execute(
        """SELECT DISTINCT ON (ticker) ticker,
                  coalesce(notes->>'sector','Unknown') AS sector,
                  coalesce(notes->>'risk_fraction','0.05') AS risk_fraction
             FROM recommendations
            WHERE status IN ('paper_candidate','paper_logged')
              AND notes->>'paper_only'='true'
              AND notes->>'no_live_execution'='true'
            ORDER BY ticker,id DESC"""
    ).fetchall()
    positions = []
    for ticker, sector, raw_risk in rows:
        try:
            risk = Decimal(str(raw_risk))
        except (InvalidOperation, ValueError, TypeError):
            risk = Decimal("0.05")
        if not risk.is_finite() or risk <= 0 or risk > Decimal("0.05"):
            risk = Decimal("0.05")
        positions.append(ExistingPosition(str(ticker).upper(), sector or "Unknown", risk))
    return tuple(positions)


def run_mid_small_shadow_orchestrator(
    conn,
    *,
    run_id,
    signal_dt: dt.date,
    decision_at: dt.datetime,
    readiness,
    account_equity,
    strategies: Sequence[str] = (
        "close_confirmed_breakout",
        "trend_pullback_reclaim",
        "volatility_contraction_breakout",
    ),
    tickers: Sequence[str] = (),
    dry_run: bool = True,
    chain_acquirer=None,
    ledger=None,
):
    """Run persisted setup candidates through every pre-release shadow stage."""
    import uuid

    from daily_multi_strategy import (
        ShadowPipelineHooks,
        ShadowPipelineRequest,
        run_shadow_pipeline,
    )
    from option_chain_provider import acquire_option_chain_snapshot

    snapshot_id = uuid.UUID(str(getattr(readiness, "universe_snapshot_id", "")))
    fingerprint = str(getattr(readiness, "universe_source_fingerprint", ""))
    request = ShadowPipelineRequest(
        run_id=uuid.UUID(str(run_id)),
        signal_dt=signal_dt,
        decision_at=decision_at,
        universe_snapshot_id=snapshot_id,
        universe_fingerprint=fingerprint,
        account_equity=account_equity,
        strategies=tuple(strategies),
        tickers=tuple(tickers),
        dry_run=dry_run,
        shadow=True,
    )
    acquire = chain_acquirer or acquire_option_chain_snapshot

    def no_shadow_write(*_args, **_kwargs):
        raise RuntimeError("recommendation writes are disabled in Task 21 shadow mode")

    hooks = ShadowPipelineHooks(
        readiness=lambda _request: readiness,
        universe=lambda _request, _readiness: {
            "snapshot_id": str(request.universe_snapshot_id),
            "fingerprint": request.universe_fingerprint,
        },
        features=lambda _request, _universe: {
            "readiness_verified": True,
            "benchmark_coverage": getattr(readiness, "benchmark_coverage_numerator", 0),
        },
        evaluations=lambda _request, _universe, _features: load_mid_small_portfolio_candidates(
            conn, run_id
        ),
        candidate_persistence=lambda _request, candidates: candidates,
        existing_positions=lambda _request: load_mid_small_existing_positions(conn),
        acquire_chain=lambda _request, candidate: acquire(
            candidate.ticker,
            signal_dt=signal_dt,
            decision_at=decision_at,
        ),
        recommendation_writer=no_shadow_write,
        outcomes=lambda _request, decisions, _dry_run: {
            "read_only": True,
            "decision_count": len(decisions),
            "underlying_writes": 0,
            "option_writes": 0,
        },
        summary=lambda _request, payload: {
            "status": payload["status"],
            "external_delivery": False,
        },
    )
    return run_shadow_pipeline(request, hooks, ledger=ledger)


def parse_mid_small_shadow_args(argv: Sequence[str] | None = None):
    """Parse the bounded Task 21 CLI; no production/release switch exists."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Run Wolfy's mid/small-cap pipeline in paper-only shadow mode"
    )
    parser.add_argument("--shadow", action="store_true", default=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--signal-dt")
    parser.add_argument("--strategy", action="append")
    parser.add_argument("--tickers")
    parser.add_argument("--run-id")
    parser.add_argument("--account-equity", default="100000")
    parser.add_argument(
        "--dsn", default="dbname=wolfy_test user=root host=/var/run/postgresql"
    )
    return parser.parse_args(argv)


def main_mid_small_shadow(argv: Sequence[str] | None = None) -> int:
    """Execute the CLI against ``wolfy_test`` with zero publication/delivery."""
    from dataclasses import asdict
    from decimal import Decimal
    import uuid

    import psycopg

    args = parse_mid_small_shadow_args(argv)
    strategies = tuple(
        args.strategy
        or (
            "close_confirmed_breakout",
            "trend_pullback_reclaim",
            "volatility_contraction_breakout",
        )
    )
    tickers = tuple(parse_tickers(args.tickers, default=()))
    with psycopg.connect(args.dsn) as conn:
        database_row = conn.execute("SELECT current_database()").fetchone()
        if database_row is None or database_row[0] != "wolfy_test":
            raise RuntimeError(
                "Task 21 shadow orchestrator is restricted to exact database wolfy_test"
            )
        decision_at = dt.datetime.now(dt.timezone.utc)
        if args.signal_dt:
            signal_dt = dt.date.fromisoformat(args.signal_dt)
            readiness = evaluate_replay_eod_readiness(
                conn,
                tickers=tickers,
                signal_dt=signal_dt,
                decision_at=decision_at,
            )
        else:
            readiness = evaluate_current_eod_readiness(
                conn, tickers=tickers, decision_at=decision_at
            )
            signal_dt = readiness.expected_session
        if not getattr(readiness, "universe_snapshot_id", None):
            print(
                json.dumps(
                    {
                        "status": "pipeline_incomplete",
                        "paper_only": True,
                        "no_live_execution": True,
                        "broker_orders_created": 0,
                        "external_deliveries": 0,
                        "eod_readiness": eod_readiness_payload(readiness),
                    },
                    sort_keys=True,
                )
            )
            return 3
        if args.run_id:
            run_id = uuid.UUID(args.run_id)
        else:
            row = conn.execute(
                """SELECT id FROM daily_evaluation_runs
                    WHERE target_session=%s AND universe_snapshot_id=%s
                    ORDER BY created_at DESC,id DESC LIMIT 1""",
                (signal_dt, readiness.universe_snapshot_id),
            ).fetchone()
            if row is None:
                print(
                    json.dumps(
                        {
                            "status": "pipeline_incomplete",
                            "incomplete_reasons": ["daily_evaluation_run_missing"],
                            "paper_only": True,
                            "no_live_execution": True,
                            "broker_orders_created": 0,
                            "external_deliveries": 0,
                        },
                        sort_keys=True,
                    )
                )
                return 3
            run_id = row[0]
        result = run_mid_small_shadow_orchestrator(
            conn,
            run_id=run_id,
            signal_dt=signal_dt,
            decision_at=decision_at,
            readiness=readiness,
            account_equity=Decimal(args.account_equity),
            strategies=strategies,
            tickers=tickers,
            dry_run=args.dry_run,
        )
    print(json.dumps(asdict(result), sort_keys=True, default=str))
    return 0 if result.status in {"shadow_complete", "no_candidates", "allocation_blocked"} else 3


def run_mid_small_underlying_shadow(
    conn,
    *,
    run_id,
    signal_dt: dt.date,
    readiness,
    dry_run: bool = True,
) -> dict:
    """Load persisted setup candidates and run the bounded Task 11 slice."""
    import uuid

    from daily_multi_strategy import run_underlying_pivot_slice
    from portfolio_allocator import PortfolioCandidate

    try:
        canonical_run_id = uuid.UUID(str(run_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("run_id must be a UUID") from exc
    rows = conn.execute(
        """SELECT candidate_id,universe_snapshot_id,ticker,strategy_id,
                  strategy_version,sector,score,entry,stop,target
             FROM setup_candidates
            WHERE run_id=%s
            ORDER BY score DESC,ticker,strategy_id""",
        (canonical_run_id,),
    ).fetchall()
    candidates = [
        PortfolioCandidate(
            candidate_id=uuid.UUID(str(row[0])),
            universe_snapshot_id=uuid.UUID(str(row[1])),
            ticker=row[2],
            strategy_id=row[3],
            strategy_version=row[4],
            sector=row[5],
            score=row[6],
            entry=row[7],
            stop=row[8],
            target=row[9],
        )
        for row in rows
    ]
    return run_underlying_pivot_slice(
        conn,
        signal_dt=signal_dt,
        readiness=readiness,
        candidates=candidates,
        dry_run=dry_run,
    )


def run_mid_small_instrument_publication(
    conn,
    *,
    recommendations: Sequence[object],
    signal_dt: dt.date,
    dry_run: bool = True,
) -> dict:
    """Route prevalidated pivot instrument decisions to the paper-only writer."""
    from eod_signals import write_pivot_paper_recommendations

    result = write_pivot_paper_recommendations(
        conn,
        recommendations=recommendations,
        signal_dt=signal_dt,
        dry_run=dry_run,
    )
    result["broker_orders_created"] = 0
    result["no_live_execution"] = True
    return result


def run_paper_recommendation_lifecycle(
    conn,
    *,
    signal_dt: dt.date,
    tickers: Sequence[str],
    as_of: dt.date | None = None,
    max_recommendations: int = 20,
    dry_run: bool = False,
) -> dict:
    """Run the Postgres paper recommendation lifecycle without broker actions."""
    from eod_signals import (
        log_approved_paper_recommendation_trades,
        write_approved_paper_recommendations,
    )
    from recommendation_outcome_review import review_open_paper_trade_setups

    selected = [str(ticker).upper() for ticker in tickers]
    recommendations = write_approved_paper_recommendations(
        conn,
        signal_dt=signal_dt,
        tickers=selected,
        max_recommendations=max_recommendations,
        dry_run=dry_run,
    )
    paper_trades = log_approved_paper_recommendation_trades(
        conn,
        signal_dt=signal_dt,
        tickers=selected,
        max_trades=max_recommendations,
        dry_run=dry_run,
    )
    outcomes = review_open_paper_trade_setups(
        conn,
        as_of=as_of or signal_dt,
        tickers=selected,
        dry_run=dry_run,
    )
    return {
        "signal_dt": signal_dt.isoformat(),
        "as_of": (as_of or signal_dt).isoformat(),
        "dry_run": dry_run,
        "recommendations": recommendations,
        "paper_trades": paper_trades,
        "outcomes": outcomes,
        "broker_orders_created": 0,
        "no_live_execution": True,
    }


def run_eod_features_signals(
    *,
    tickers_csv_value: str | None = None,
    signal_dt_value: str | None = None,
    dry_run: bool = False,
) -> int:
    """Run deterministic signal generation and approved-strategy setup gate."""
    import psycopg
    from eod_signals import propose_approved_setups

    tickers = parse_tickers(tickers_csv_value, default=CORE_EOD_UNIVERSE)
    with psycopg.connect("dbname=wolfy user=root host=/var/run/postgresql") as conn:
        if signal_dt_value is None:
            readiness = evaluate_current_eod_readiness(conn, tickers=tickers)
            signal_dt = readiness.expected_session
        else:
            signal_dt = dt.date.fromisoformat(signal_dt_value)
            readiness = evaluate_replay_eod_readiness(
                conn,
                tickers=tickers,
                signal_dt=signal_dt,
            )
        for_session = next_business_day(signal_dt)
        if not readiness.publishable:
            print(
                json.dumps(
                    {
                        "dry_run": dry_run,
                        "writes": False,
                        "status": "blocked_incomplete_eod_readiness",
                        "eod_readiness": eod_readiness_payload(readiness),
                    },
                    sort_keys=True,
                )
            )
            return 3
        if dry_run:
            gate = propose_approved_setups(
                conn,
                signal_dt=signal_dt,
                for_session=for_session,
                tickers=tickers,
                dry_run=True,
            )
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "writes": False,
                        "signal_dt": str(signal_dt),
                        "for_session": str(for_session),
                        "eod_readiness": eod_readiness_payload(readiness),
                        "approved_gate": gate,
                    },
                    sort_keys=True,
                    default=str,
                )
            )
            return 0

        # Free/local technical context must exist before the research-only
        # options-volatility strategy is generated. No paid APIs or trials.
        from free_technical_data import (
            compute_and_store_breadth,
            compute_and_store_options_features,
            ingest_free_sources,
            fetch_nasdaq_short_interest,
            snapshot_current_universe,
            store_nasdaq_short_interest,
        )

        # Fetch live public datasets only during the normal current EOD run.
        # An explicit --signal-dt is a replay and must never relabel today's
        # Cboe/Nasdaq pages as observations from a historical session.
        if signal_dt_value is None:
            snapshot_current_universe(conn, signal_dt=signal_dt)
            ingest_free_sources(conn, as_of=signal_dt)
            nasdaq_rows = fetch_nasdaq_short_interest(tickers, published_at=dt.date.today())
            store_nasdaq_short_interest(
                conn,
                nasdaq_rows,
                source="nasdaq-public-per-symbol-short-interest",
                source_url="https://api.nasdaq.com/api/quote/{symbol}/short-interest?assetclass=stocks",
            )
        compute_and_store_options_features(conn, tickers=tickers, end_dt=signal_dt)
        compute_and_store_breadth(conn, signal_dt=signal_dt)

    cmd = [
        sys.executable,
        str(WOLFY_DIR / "eod_signals.py"),
        "--tickers",
        ",".join(tickers),
        "--signal-dt",
        str(signal_dt),
        "--for-session",
        str(for_session),
        "--create-setups",
    ]
    rc = subprocess.call(cmd)
    if rc != 0:
        return rc
    with psycopg.connect("dbname=wolfy user=root host=/var/run/postgresql") as conn:
        lifecycle = run_paper_recommendation_lifecycle(
            conn,
            signal_dt=signal_dt,
            tickers=tickers,
            as_of=signal_dt,
            max_recommendations=20,
            dry_run=False,
        )
    print(json.dumps({"paper_recommendation_lifecycle": lifecycle}, sort_keys=True, default=str))
    return 0
