#!/usr/bin/env python3
"""Silent script-only Wolfy scanner snapshot helper.

Runs the deterministic delayed/free scanner and persists scanner_runs/scanner_results
without spending LLM tokens. Designed for Hermes no_agent cron jobs: successful runs
emit nothing; only threshold failures print a compact alert.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import sqlite3
import sys
from pathlib import Path
from typing import Any

import wolfy_scanner

DEFAULT_DB = Path('/root/.hermes/wolfy/wolfy.db')


class SnapshotAlert(RuntimeError):
    """Raised when a scanner snapshot should alert the no_agent cron."""


def _active_universe_count(db_path: Path) -> int:
    con = sqlite3.connect(db_path)
    try:
        wolfy_scanner.ensure_universe_tables(con)
        return int(con.execute('SELECT COUNT(*) FROM universe_symbols WHERE active=1').fetchone()[0])
    finally:
        con.close()


def _resolve_symbols(db_path: Path, universe: str, ticker_list: str | None, refresh_universe: bool) -> list[str]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        wolfy_scanner.ensure_universe_tables(con)
        if refresh_universe or con.execute('SELECT COUNT(*) FROM universe_symbols WHERE active=1').fetchone()[0] == 0:
            # Suppress transient source warnings on successful runs; threshold checks below
            # decide whether no_agent should notify the user.
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                wolfy_scanner.refresh_universe_cache(con)
        return wolfy_scanner.resolve_symbols(con, universe, ticker_list)
    finally:
        con.close()


def run_snapshot(
    *,
    db_path: Path | str = DEFAULT_DB,
    universe: str = 'expanded',
    ticker_list: str | None = None,
    max_workers: int = 8,
    min_ranked: int = 1,
    max_failure_rate: float = 0.35,
    refresh_universe: bool = False,
) -> dict[str, Any]:
    """Run and persist one scanner snapshot, returning compact status.

    This function intentionally captures scanner stdout/stderr so normal no_agent
    cron ticks remain silent. It raises SnapshotAlert for material data-quality
    problems that should be delivered to the user/operator.
    """
    db_path = Path(db_path)
    symbols = _resolve_symbols(db_path, universe, ticker_list, refresh_universe)
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
        'ranked_count': len(ranked),
        'failure_count': failure_count,
        'failure_rate': failure_rate,
        'active_universe_count': _active_universe_count(db_path),
    }
    alerts = []
    if len(ranked) < min_ranked:
        alerts.append(f"ranked_count={len(ranked)} below min_ranked={min_ranked}")
    if failure_rate > max_failure_rate:
        alerts.append(f"failure_rate={failure_rate:.2f} above max_failure_rate={max_failure_rate:.2f}")
    if not symbols:
        alerts.append('symbol_count=0; scanner universe is empty')
    if alerts:
        sample_failures = ', '.join(f'{k}: {v}' for k, v in list(failures.items())[:5])
        detail = '; '.join(alerts)
        if sample_failures:
            detail = f'{detail}; sample_failures={sample_failures}'
        raise SnapshotAlert(detail)
    return status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Silent Wolfy intraday scanner snapshot helper')
    parser.add_argument('--db-path', default=str(DEFAULT_DB), help='Wolfy SQLite compatibility DB path')
    parser.add_argument('--universe', choices=['core', 'expanded', 'etf', 'ticker-list'], default='expanded')
    parser.add_argument('--ticker-list', help='Comma-separated tickers for --universe ticker-list smoke runs')
    parser.add_argument('--max-workers', type=int, default=8)
    parser.add_argument('--min-ranked', type=int, default=1)
    parser.add_argument('--max-failure-rate', type=float, default=0.35)
    parser.add_argument('--refresh-universe', action='store_true')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run_snapshot(
            db_path=Path(args.db_path),
            universe=args.universe,
            ticker_list=args.ticker_list,
            max_workers=args.max_workers,
            min_ranked=args.min_ranked,
            max_failure_rate=args.max_failure_rate,
            refresh_universe=args.refresh_universe,
        )
    except Exception as exc:
        print(f'Wolfy intraday scanner snapshot alert: {exc}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
