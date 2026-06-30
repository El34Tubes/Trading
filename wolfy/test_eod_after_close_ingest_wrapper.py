from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


WRAPPER = Path('/root/.hermes/scripts/wolfy_eod_after_close_ingest.py')
SHARD_1 = Path('/root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_1.py')


def _load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_default_live_ingest_requests_two_year_history(monkeypatch):
    """Live EOD ingest should maintain enough history for meaningful walk-forward backtests."""
    module = _load_script(WRAPPER, 'wolfy_eod_after_close_ingest_wrapper')
    captured = {}

    def fake_call(cmd):
        captured['cmd'] = cmd
        return 0

    monkeypatch.setattr(module.run_eod_ingest.__globals__['subprocess'], 'call', fake_call)
    monkeypatch.setattr(sys, 'argv', ['wolfy_eod_after_close_ingest.py'])

    assert module.main() == 0

    cmd = captured['cmd']
    assert '--days' in cmd
    days = int(cmd[cmd.index('--days') + 1])
    assert days >= 730
    assert '--source' in cmd
    assert cmd[cmd.index('--source') + 1] == 'massive'


def test_shard_wrapper_uses_shared_shard_config(monkeypatch):
    module = _load_script(SHARD_1, 'wolfy_eod_after_close_ingest_shard_1')
    captured = {}

    def fake_call(cmd):
        captured['cmd'] = cmd
        return 0

    monkeypatch.setattr(module.run_eod_ingest_shard.__globals__['subprocess'], 'call', fake_call)

    assert module.main() == 0

    cmd = captured['cmd']
    assert '--no-validate' in cmd
    assert '--tickers' in cmd
    tickers = cmd[cmd.index('--tickers') + 1]
    assert tickers == 'SPY,QQQ,IWM,DIA,XLK,XLF,XLY,XLI,XLE'
    assert '--days' in cmd
    assert int(cmd[cmd.index('--days') + 1]) >= 730
