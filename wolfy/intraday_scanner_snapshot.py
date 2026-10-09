#!/usr/bin/env python3
"""Silent script-only Wolfy scanner snapshot helper.

Runs the deterministic delayed/free scanner and persists scanner_runs/scanner_results
to Postgres only. Designed for Hermes no_agent cron jobs: successful runs
emit nothing; only threshold failures print a compact alert.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

import wolfy_scanner
from wolfy_postgres_pipeline import load_universe_postgres, refresh_universe_cache_postgres


class SnapshotAlert(RuntimeError):
    """Raised when a scanner snapshot should alert the no_agent cron."""


def _active_universe_count(universe: str, symbols: list[str] | None = None) -> int:
    # The caller has already resolved the authoritative universe. Reuse it so
    # SQLite compatibility tests and bounded smokes never reach into live
    # Postgres merely to assemble status metadata.
    if symbols is not None:
        return len(symbols)
    if universe == 'ticker-list':
        return 0
    return len(load_universe_postgres(universe))


def _resolve_symbols(universe: str, ticker_list: str | None, refresh_universe: bool, db_path: Path | None = None) -> list[str]:
    if universe == 'ticker-list':
        if not ticker_list:
            raise SnapshotAlert('ticker-list universe requires --ticker-list')
        return wolfy_scanner.resolve_symbols(None, universe, ticker_list)  # type: ignore[arg-type]
    if db_path is not None:
        con = sqlite3.connect(db_path)
        try:
            return wolfy_scanner.resolve_symbols(con, universe, ticker_list)
        finally:
            con.close()
    if refresh_universe:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            refresh_universe_cache_postgres({'core': wolfy_scanner.core_records(), 'major_etf': wolfy_scanner.etf_records()})
    symbols = load_universe_postgres(universe)
    if not symbols:
        source_records = {'core': wolfy_scanner.core_records(), 'major_etf': wolfy_scanner.etf_records()}
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            refresh_universe_cache_postgres(source_records)
        symbols = load_universe_postgres(universe)
    return symbols


def _bounded_symbols(symbols: list[str], max_symbols: int | None) -> list[str]:
    """Return a rotating subset that always carries the RS benchmarks."""
    benchmarks = ['QQQ', 'SPY']
    candidates = sorted(set(symbols) - set(benchmarks))
    if not max_symbols or max_symbols <= 0:
        return sorted(candidates + benchmarks)
    max_symbols = max(max_symbols, len(benchmarks))
    candidate_slots = max_symbols - len(benchmarks)
    if len(candidates) <= candidate_slots:
        return sorted(candidates + benchmarks)
    now = datetime.now()
    start = (now.timetuple().tm_yday * 24 + now.hour) * max(candidate_slots, 1)
    start %= len(candidates)
    rotated = candidates[start:] + candidates[:start]
    return sorted(rotated[:candidate_slots] + benchmarks)


def run_snapshot(
    *,
    universe: str = 'expanded',
    ticker_list: str | None = None,
    max_workers: int = 8,
    min_ranked: int = 1,
    max_failure_rate: float = 0.35,
    as_of_date: str | None = None,
    max_data_lag_days: int = 3,
    refresh_universe: bool = False,
    max_symbols: int | None = 32,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Run and persist one scanner snapshot, returning compact status."""
    all_symbols = _resolve_symbols(universe, ticker_list, refresh_universe, db_path=db_path)
    symbols = _bounded_symbols(all_symbols, max_symbols)
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
        ranked, failures = wolfy_scanner.run_scan(
            symbols,
            db_path=db_path,
            persist=True,
            universe=universe,
            max_workers=max_workers,
        )
    symbol_count = len(symbols)
    failure_count = len(failures)
    failure_rate = failure_count / symbol_count if symbol_count else 1.0
    status = {
        'universe': universe,
        'symbol_count': symbol_count,
        'total_universe_symbols': len(all_symbols),
        'max_symbols': max_symbols,
        'ranked_count': len(ranked),
        'failure_count': failure_count,
        'failure_rate': failure_rate,
        'active_universe_count': _active_universe_count(universe, all_symbols),
        'latest_data_date': max((str(row.get('date')) for _score, _ticker, row in ranked if row.get('date')), default=None),
    }
    alerts = []
    if len(ranked) < min_ranked:
        alerts.append(f"ranked_count={len(ranked)} below min_ranked={min_ranked}")
    if failure_rate > max_failure_rate:
        alerts.append(f"failure_rate={failure_rate:.2f} above max_failure_rate={max_failure_rate:.2f}")
    if not symbols:
        alerts.append('symbol_count=0; scanner universe is empty')
    latest = status['latest_data_date']
    if latest:
        if not (db_path is not None and as_of_date is None):
            try:
                lag = (date.fromisoformat(as_of_date) if as_of_date else date.today()) - date.fromisoformat(latest)
                status['data_lag_days'] = lag.days
                if lag.days > max_data_lag_days:
                    alerts.append(
                        f"latest_data_date={latest} is stale versus as_of_date={as_of_date}; "
                        f"lag_days={lag.days} above max_data_lag_days={max_data_lag_days}"
                    )
            except ValueError:
                alerts.append(f'latest_data_date={latest} is not ISO date')
    elif min_ranked > 0 or ranked:
        alerts.append('latest_data_date missing from ranked scanner output')
    if alerts:
        detail = ' '.join(alerts)
        raise SnapshotAlert(
            f"Wolfy intraday scanner snapshot alert: universe={universe} symbols={symbol_count} ranked={len(ranked)} failures={failure_count}; {detail}"
        )
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Silent Wolfy deterministic scanner snapshot watchdog')
    parser.add_argument('--universe', default='expanded', choices=['core', 'expanded', 'ticker-list'])
    parser.add_argument('--ticker-list')
    parser.add_argument('--max-workers', type=int, default=8)
    parser.add_argument('--min-ranked', type=int, default=1)
    parser.add_argument('--max-failure-rate', type=float, default=0.35)
    parser.add_argument('--as-of-date')
    parser.add_argument('--max-data-lag-days', type=int, default=3)
    parser.add_argument('--refresh-universe', action='store_true')
    parser.add_argument('--max-symbols', type=int, default=32, help='Bound tickers per cron run; <=0 scans full universe')
    parser.add_argument('--db-path', type=Path, help='SQLite compatibility DB path for tests/legacy smokes only')
    args = parser.parse_args(argv)
    try:
        run_snapshot(
            universe=args.universe,
            ticker_list=args.ticker_list,
            max_workers=args.max_workers,
            min_ranked=args.min_ranked,
            max_failure_rate=args.max_failure_rate,
            as_of_date=args.as_of_date,
            max_data_lag_days=args.max_data_lag_days,
            refresh_universe=args.refresh_universe,
            max_symbols=args.max_symbols,
            db_path=args.db_path,
        )
        return 0
    except SnapshotAlert as exc:
        print(str(exc))
        return 1
    except Exception as exc:
        print(f'Wolfy intraday scanner snapshot alert: {type(exc).__name__}: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
