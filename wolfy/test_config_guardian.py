#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GUARDIAN = ROOT / "guardian" / "config_guardian.py"


def write_min_home(home: Path) -> None:
    (home / "cron").mkdir(parents=True)
    (home / "config.yaml").write_text("agent:\n  max_turns: 90\n")
    (home / "cron" / "jobs.json").write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "92f31b95fccc",
                        "name": "Wolfy daily optimization planner and implementer",
                        "enabled": True,
                        "state": "scheduled",
                    }
                ]
            },
            indent=2,
        )
        + "\n"
    )


def test_config_guardian_restores_known_good_on_broken_config_and_expired_probation(tmp_path: Path) -> None:
    home = tmp_path / "hermes"
    home.mkdir()
    write_min_home(home)

    first = subprocess.run(
        [sys.executable, str(GUARDIAN), "--home", str(home), "--skip-cli", "--snapshot", "--dsn", "dbname=wolfy user=root host=/var/run/postgresql"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert first.returncode == 0, first.stdout
    assert "GUARDIAN=ok" in first.stdout
    known_good = home / "wolfy" / "guardian" / "known_good"
    assert any(known_good.iterdir())

    (home / "config.yaml").write_text("agent: [broken\n")
    expired = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)).isoformat()
    probation = home / "wolfy" / "guardian" / "probation.json"
    probation.write_text(json.dumps({"change": "test-broken-config", "expires_at": expired}) + "\n")

    second = subprocess.run(
        [sys.executable, str(GUARDIAN), "--home", str(home), "--skip-cli", "--dsn", "dbname=wolfy user=root host=/var/run/postgresql"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert second.returncode == 1, second.stdout
    assert "GUARDIAN=restored" in second.stdout
    assert (home / "config.yaml").read_text() == "agent:\n  max_turns: 90\n"
    assert not probation.exists()
    log = home / "wolfy" / "guardian" / "guardian.log"
    assert "ROLLBACK" in log.read_text()
