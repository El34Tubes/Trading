from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


WRAPPER = Path('/root/.hermes/scripts/wolfy_eod_after_close_ingest.py')


def _load_wrapper():
    spec = importlib.util.spec_from_file_location('wolfy_eod_after_close_ingest_wrapper', WRAPPER)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_default_live_ingest_requests_two_year_history(monkeypatch):
    """Live EOD ingest should maintain enough history for meaningful walk-forward backtests."""
    module = _load_wrapper()
    captured = {}

    def fake_call(cmd):
        captured['cmd'] = cmd
        return 0

    monkeypatch.setattr(module.subprocess, 'call', fake_call)
    monkeypatch.setattr(sys, 'argv', ['wolfy_eod_after_close_ingest.py'])

    assert module.main() == 0

    cmd = captured['cmd']
    assert '--days' in cmd
    days = int(cmd[cmd.index('--days') + 1])
    assert days >= 730
