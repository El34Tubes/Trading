#!/usr/bin/env python3
"""Task 23 mid/small entrypoint; omitted subcommand remains safe shadow mode."""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys
from typing import Sequence

WOLFY_DIR = Path(__file__).resolve().parents[1] / "wolfy"
if str(WOLFY_DIR) not in sys.path:
    sys.path.insert(0, str(WOLFY_DIR))

from orchestration_runner import main_mid_small_shadow  # noqa: E402
from production_release import (  # noqa: E402
    DEFAULT_RELEASE_ARTIFACT,
    bootstrap_source_cache,
    load_release_artifact,
    rollback_release,
    run_production_canary,
)

_COMMANDS = frozenset({"shadow", "bootstrap", "canary", "scheduled", "rollback"})


def _artifact_parser(command: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"wolfy_mid_small_daily.py {command}")
    parser.add_argument("--artifact", default=str(DEFAULT_RELEASE_ARTIFACT))
    return parser


def _bootstrap(argv: Sequence[str]) -> int:
    parser = _artifact_parser("bootstrap")
    parser.add_argument("--source-cache", required=True)
    parser.add_argument("--signal-dt")
    parser.add_argument("--account-equity", default="100000")
    parser.add_argument("--canary-evidence-path")
    parser.add_argument("--rollback-state-path")
    args = parser.parse_args(argv)
    result = bootstrap_source_cache(
        args.source_cache,
        artifact_path=args.artifact,
        signal_dt=date.fromisoformat(args.signal_dt) if args.signal_dt else None,
        account_equity=args.account_equity,
        canary_evidence_path=args.canary_evidence_path,
        rollback_state_path=args.rollback_state_path,
    )
    print(json.dumps(result, sort_keys=True, default=str))
    return 0


def _canary(argv: Sequence[str], *, scheduled: bool) -> int:
    command = "scheduled" if scheduled else "canary"
    args = _artifact_parser(command).parse_args(argv)
    result = run_production_canary(args.artifact, scheduled=scheduled)
    print(json.dumps(result, sort_keys=True, default=str))
    return 0


def _rollback(argv: Sequence[str]) -> int:
    args = _artifact_parser("rollback").parse_args(argv)
    release = load_release_artifact(args.artifact)
    result = rollback_release(release, args.artifact)
    print(json.dumps(result, sort_keys=True, default=str))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch an explicit release action; default and unknown options are shadow."""
    values = list(sys.argv[1:] if argv is None else argv)
    command = values.pop(0) if values and values[0] in _COMMANDS else "shadow"
    if command == "shadow":
        return main_mid_small_shadow(values)
    if command == "bootstrap":
        return _bootstrap(values)
    if command == "canary":
        return _canary(values, scheduled=False)
    if command == "scheduled":
        return _canary(values, scheduled=True)
    if command == "rollback":
        return _rollback(values)
    raise AssertionError("unreachable command")


if __name__ == "__main__":
    raise SystemExit(main())
