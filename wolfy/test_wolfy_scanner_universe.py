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


def test_metrics_calculates_volume_breakout_squeeze_gap_and_trend_factors():
    rows = []
    start = dt.date(2026, 1, 1)
    for i in range(80):
        close = 95 + i * 0.2
        open_ = close - 0.3
        high = close + 1.0
        low = close - 1.0
        volume = 1_000_000
        if i >= 75:
            volume = 2_000_000
        rows.append(((start + dt.timedelta(days=i)).isoformat(), open_, high, low, close, volume))
    prior_high20 = max(r[2] for r in rows[-20:])
    rows[-1] = (rows[-1][0], rows[-2][4] + 2.0, prior_high20 + 0.5, prior_high20 - 1.0, prior_high20 + 0.2, 4_000_000)

    m = wolfy_scanner.metrics(rows)

    assert m['volume_surge_1d_20'] > 3.0
    assert m['volume_surge_5d_20'] > 1.0
    assert m['volume_surge_1d_50'] > 3.0
    assert m['breakout_20d_pct'] > 0
    assert m['trend_regime'] == 'bull_50_200'
    assert m['atr_pct'] > 0
    assert m['squeeze_ratio'] < 1.0
    assert m['squeeze_flag'] == 1
    assert m['gap_reversal_flag'] == 'gap_up_hold'
    assert m['liquidity_spread_proxy'] > 0


def test_rank_metrics_uses_relative_strength_and_returns_rank_reasons():
    data = {
        'SPY': {'r20': 2, 'r60': 3},
        'QQQ': {'r20': 5, 'r60': 6},
        'LEADER': {
            'date': '2026-06-01', 'close': 100, 'r5': 4, 'r20': 12, 'r60': 20,
            'vs20': 4, 'vs50': 8, 'atr': 3, 'avgvol': 5_000_000, 'hi20': 101, 'lo20': 80,
            'volume_surge_1d_20': 2.5, 'volume_surge_5d_20': 1.7, 'breakout_20d_pct': 1.2,
            'atr_pct': 3.0, 'squeeze_ratio': 0.7, 'squeeze_flag': 1, 'gap_reversal_flag': 'none',
            'extension_penalty': 0, 'liquidity_spread_proxy': 0.08, 'trend_regime': 'bull_50_200',
        },
        'LAGGARD': {
            'date': '2026-06-01', 'close': 50, 'r5': 1, 'r20': 4, 'r60': 2,
            'vs20': 18, 'vs50': 5, 'atr': 2, 'avgvol': 5_000_000, 'hi20': 55, 'lo20': 45,
            'volume_surge_1d_20': 0.8, 'volume_surge_5d_20': 0.9, 'breakout_20d_pct': -3.0,
            'atr_pct': 4.0, 'squeeze_ratio': 1.4, 'squeeze_flag': 0, 'gap_reversal_flag': 'gap_up_reversal',
            'extension_penalty': 9, 'liquidity_spread_proxy': 0.2, 'trend_regime': 'mixed',
        },
    }

    ranked = wolfy_scanner.rank_metrics(data)

    assert [symbol for _score, symbol, _metrics in ranked] == ['LEADER', 'LAGGARD']
    leader = ranked[0][2]
    assert leader['rs_spy_20'] == 10
    assert leader['rs_qqq_20'] == 7
    assert 'RS+10.0 vs SPY' in leader['rank_reasons']
    assert 'volume surge' in leader['rank_reasons']
    assert 'squeeze' in leader['rank_reasons']


def test_persist_scan_adds_notes_json_with_new_factor_payload(tmp_path):
    db = tmp_path / 'wolfy.db'
    con = sqlite3.connect(db)
    con.executescript('''
        CREATE TABLE scanner_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_time TEXT NOT NULL DEFAULT (datetime('now')),
          data_source TEXT NOT NULL,
          universe TEXT,
          notes TEXT
        );
        CREATE TABLE scanner_results (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id INTEGER NOT NULL,
          ticker TEXT NOT NULL,
          score REAL,
          data_date TEXT,
          close REAL,
          r5 REAL, r20 REAL, r60 REAL,
          vs20 REAL, vs50 REAL,
          atr REAL,
          avg_volume REAL,
          high20 REAL,
          low20 REAL,
          extension_penalty REAL,
          liquidity_pass INTEGER,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    ''')
    con.close()
    metrics = {
        'date': '2026-06-01', 'close': 100, 'r5': 4, 'r20': 12, 'r60': 20,
        'vs20': 4, 'vs50': 8, 'atr': 3, 'avgvol': 5_000_000, 'hi20': 101, 'lo20': 80,
        'volume_surge_1d_20': 2.5, 'volume_surge_5d_20': 1.7, 'volume_surge_1d_50': 2.2,
        'volume_surge_5d_50': 1.5, 'breakout_20d_pct': 1.2, 'trend_regime': 'bull_50_200',
        'atr_pct': 3.0, 'squeeze_ratio': 0.7, 'squeeze_flag': 1, 'gap_reversal_flag': 'none',
        'extension_penalty': 0, 'liquidity_spread_proxy': 0.08, 'rs_spy_20': 10, 'rs_qqq_20': 7,
        'rank_reasons': 'RS+10.0 vs SPY; volume surge; squeeze',
    }

    run_id = wolfy_scanner.persist_scan([(42.0, 'LEADER', metrics)], db, 'ticker-list')

    con = sqlite3.connect(db)
    columns = [row[1] for row in con.execute('PRAGMA table_info(scanner_results)').fetchall()]
    payload = con.execute("SELECT notes_json FROM scanner_results WHERE ticker='LEADER'").fetchone()[0]
    con.close()
    parsed = wolfy_scanner.json.loads(payload)
    assert run_id == 1
    assert 'notes_json' in columns
    assert parsed['volume_surge_1d_20'] == 2.5
    assert parsed['rank_reasons'] == 'RS+10.0 vs SPY; volume surge; squeeze'
