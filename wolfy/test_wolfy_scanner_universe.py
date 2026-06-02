import datetime as dt
import sqlite3

import wolfy_scanner


def make_rows(close=100.0, volume=2_000_000, days=90):
    rows = []
    start = dt.date(2026, 1, 1)
    for i in range(days):
        c = close + i * 0.5
        rows.append(((start + dt.timedelta(days=i)).isoformat(), c - 1, c + 1, c - 2, c, volume))
    return rows


def test_expanded_universe_cache_persists_at_least_300_symbols_with_metadata():
    con = sqlite3.connect(':memory:')
    symbols = [
        {
            'symbol': f'T{i:03d}',
            'name': f'Test Company {i}',
            'source': 'test_sp500',
            'sector': 'Technology' if i % 2 == 0 else 'Industrials',
            'is_etf': 0,
        }
        for i in range(305)
    ]

    wolfy_scanner.ensure_universe_tables(con)
    count = wolfy_scanner.refresh_universe_cache(
        con,
        source_records={'test_sp500': symbols},
        now='2026-06-01T12:00:00+00:00',
    )
    loaded = wolfy_scanner.load_universe(con, 'expanded')

    assert count >= 305
    assert len(loaded) >= 300
    assert loaded[0] == 'T000'
    row = con.execute(
        "SELECT symbol, name, source, sector, is_etf, active, last_seen FROM universe_symbols WHERE symbol='T000'"
    ).fetchone()
    assert row == ('T000', 'Test Company 0', 'test_sp500', 'Technology', 0, 1, '2026-06-01T12:00:00+00:00')


def test_universe_modes_filter_core_etf_and_ticker_list():
    con = sqlite3.connect(':memory:')
    wolfy_scanner.ensure_universe_tables(con)
    wolfy_scanner.refresh_universe_cache(
        con,
        source_records={
            'core': [
                {'symbol': 'AAPL', 'name': 'Apple', 'source': 'core', 'sector': 'Technology', 'is_etf': 0},
                {'symbol': 'SPY', 'name': 'SPDR S&P 500 ETF', 'source': 'core_etf', 'sector': 'ETF', 'is_etf': 1},
            ],
            'theme_etf': [
                {'symbol': 'SMH', 'name': 'VanEck Semiconductor ETF', 'source': 'theme_etf', 'sector': 'ETF', 'is_etf': 1},
            ],
            'sp500': [
                {'symbol': 'MSFT', 'name': 'Microsoft', 'source': 'sp500', 'sector': 'Technology', 'is_etf': 0},
            ],
        },
        now='2026-06-01T12:00:00+00:00',
    )

    assert wolfy_scanner.load_universe(con, 'core') == ['AAPL', 'SPY']
    assert wolfy_scanner.load_universe(con, 'etf') == ['SMH', 'SPY']
    assert wolfy_scanner.resolve_symbols(con, 'ticker-list', 'tsla, nvda,SPY') == ['TSLA', 'NVDA', 'SPY']


def test_run_scan_skips_fetch_failures_and_still_returns_ranked_results(monkeypatch):
    def fake_fetch(symbol, days=420):
        if symbol == 'BAD':
            raise RuntimeError('simulated yahoo outage')
        return make_rows(close=100 if symbol == 'SPY' else 120)

    monkeypatch.setattr(wolfy_scanner, 'fetch', fake_fetch)

    ranked, failures = wolfy_scanner.run_scan(['SPY', 'GOOD', 'BAD'], db_path=None, persist=False)

    assert [symbol for _score, symbol, _metrics in ranked] == ['GOOD']
    assert failures == {'BAD': 'simulated yahoo outage'}
