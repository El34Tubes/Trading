from __future__ import annotations

import json
from datetime import date
from pathlib import Path


def test_cli_normalizes_chain_payload_shape(tmp_path: Path):
    from run_experimental_options_forward_test import load_chain_snapshot
    path = tmp_path / "chain.json"
    path.write_text(json.dumps({"fetched_at":"2026-08-12T20:00:00Z","source":"unit-read-only","chains":{"abc":[{"symbol":"ABC1"}]}}))
    snapshot = load_chain_snapshot(path)
    assert snapshot["source"] == "unit-read-only"
    assert snapshot["chains"] == {"ABC": [{"symbol":"ABC1"}]}
