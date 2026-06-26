import io
import sqlite3

import pytest

import intraday_scanner_snapshot as snapshot


def test_snapshot_success_stays_silent_and_persists_scan(monkeypatch, tmp_path, capsys):
    db = tmp_path / 'wolfy.db'
    con = sqlite3.connect(db)
    snapshot.wolfy_scanner.ensure_universe_tables(con)
    snapshot.wolfy_scanner.refresh_universe_cache(
        con,
        source_records={'core': [
            {'symbol': 'SPY', 'name': 'SPY', 'source': 'core_etf', 'sector': 'ETF', 'is_etf': 1},
            {'symbol': 'QQQ', 'name': 'QQQ', 'source': 'core_etf', 'sector': 'ETF', 'is_etf': 1},
            {'symbol': 'LEADER', 'name': 'Leader Inc', 'source': 'core', 'sector': 'Technology', 'is_etf': 0},
        ]},
        now='2026-06-04T14:30:00+00:00',
    )
    con.close()

    def fake_run_scan(symbols, db_path, persist, universe, max_workers):
        assert symbols == ['LEADER', 'QQQ', 'SPY']
        assert db_path == db
        assert persist is True
        assert universe == 'core'
        print('csv output that must not leak')
        print('# db_run_id=99', file=snapshot.sys.stderr)
        return [(5.0, 'LEADER', {'date': '2026-06-03'})], {}

    monkeypatch.setattr(snapshot.wolfy_scanner, 'run_scan', fake_run_scan)

    status = snapshot.run_snapshot(db_path=db, universe='core', max_workers=1, min_ranked=1, max_failure_rate=0.5)

    captured = capsys.readouterr()
    assert captured.out == ''
    assert captured.err == ''
    assert status['ranked_count'] == 1
    assert status['failure_count'] == 0
    assert status['symbol_count'] == 3


def test_snapshot_alerts_when_ranked_rows_below_threshold(monkeypatch, tmp_path):
    db = tmp_path / 'wolfy.db'
    con = sqlite3.connect(db)
    snapshot.wolfy_scanner.ensure_universe_tables(con)
    snapshot.wolfy_scanner.refresh_universe_cache(
        con,
        source_records={'core': [
            {'symbol': 'SPY', 'name': 'SPY', 'source': 'core_etf', 'sector': 'ETF', 'is_etf': 1},
            {'symbol': 'QQQ', 'name': 'QQQ', 'source': 'core_etf', 'sector': 'ETF', 'is_etf': 1},
        ]},
        now='2026-06-04T14:30:00+00:00',
    )
    con.close()

    monkeypatch.setattr(snapshot.wolfy_scanner, 'run_scan', lambda *args, **kwargs: ([], {}))

    with pytest.raises(snapshot.SnapshotAlert) as excinfo:
        snapshot.run_snapshot(db_path=db, universe='core', min_ranked=1)

    assert 'ranked_count=0 below min_ranked=1' in str(excinfo.value)


def test_cli_prints_single_alert_and_returns_nonzero_on_threshold(monkeypatch, tmp_path, capsys):
    db = tmp_path / 'wolfy.db'
    con = sqlite3.connect(db)
    snapshot.wolfy_scanner.ensure_universe_tables(con)
    snapshot.wolfy_scanner.refresh_universe_cache(
        con,
        source_records={'core': [
            {'symbol': 'SPY', 'name': 'SPY', 'source': 'core_etf', 'sector': 'ETF', 'is_etf': 1},
        ]},
        now='2026-06-04T14:30:00+00:00',
    )
    con.close()
    monkeypatch.setattr(snapshot.wolfy_scanner, 'run_scan', lambda *args, **kwargs: ([], {'SPY': 'timeout'}))

    rc = snapshot.main(['--db-path', str(db), '--universe', 'core', '--min-ranked', '1', '--max-failure-rate', '0'])

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err == ''
    assert captured.out.startswith('Wolfy intraday scanner snapshot alert:')
    assert 'failure_rate=1.00 above max_failure_rate=0.00' in captured.out
