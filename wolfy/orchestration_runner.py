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
    day = day + dt.timedelta(days=1)
    while day.weekday() >= 5:
        day += dt.timedelta(days=1)
    return day


def latest_price_date(conn, tickers: list[str]) -> dt.date:
    row = conn.execute("SELECT max(dt) FROM prices WHERE ticker = ANY(%s)", (tickers,)).fetchone()
    if not row or row[0] is None:
        raise RuntimeError("no EOD prices available for signal generation")
    return row[0]


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
        signal_dt = dt.date.fromisoformat(signal_dt_value) if signal_dt_value else latest_price_date(conn, tickers)
        for_session = next_business_day(signal_dt)
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
    return subprocess.call(cmd)
