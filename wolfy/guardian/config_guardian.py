#!/usr/bin/env python3
"""Deterministic config/cron guardian for Wolfy orchestration.

Snapshots config.yaml and cron/jobs.json, validates basic Hermes health, and
restores the most recent known-good snapshot when config/cron health fails or
an unconfirmed probation marker expires.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None
try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

DEFAULT_DSN = "dbname=wolfy user=root host=/var/run/postgresql"
OPTIMIZER_JOB_ID = "92f31b95fccc"
KNOWN_GOOD_SNAPSHOT_RETENTION = 24


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def stamp(ts: dt.datetime | None = None) -> str:
    return (ts or utc_now()).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def guardian_dir(home: Path) -> Path:
    return home / "wolfy" / "guardian"


def known_good_dir(home: Path) -> Path:
    return guardian_dir(home) / "known_good"


def manifest_path(home: Path) -> Path:
    return guardian_dir(home) / "manifest.json"


def log_path(home: Path) -> Path:
    return guardian_dir(home) / "guardian.log"


def probation_path(home: Path) -> Path:
    return guardian_dir(home) / "probation.json"


def protected_paths(home: Path) -> dict[str, Path]:
    return {
        "config.yaml": home / "config.yaml",
        "cron/jobs.json": home / "cron" / "jobs.json",
    }


def log(home: Path, message: str) -> None:
    path = log_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{utc_now().isoformat()} {message}\n")


def load_manifest(home: Path) -> dict:
    path = manifest_path(home)
    if not path.exists():
        return {"latest_snapshot": None, "hashes": {}}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"latest_snapshot": None, "hashes": {}}


def save_manifest(home: Path, manifest: dict) -> None:
    path = manifest_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def current_hashes(home: Path) -> dict[str, str]:
    hashes = {}
    for rel, path in protected_paths(home).items():
        if path.exists():
            hashes[rel] = sha256_file(path)
        else:
            hashes[rel] = "MISSING"
    return hashes


def snapshot(home: Path, reason: str = "manual") -> Path:
    root = known_good_dir(home)
    dest = root / stamp()
    # Avoid collisions in tests/rapid repeated calls.
    suffix = 0
    base = dest
    while dest.exists():
        suffix += 1
        dest = Path(str(base) + f"_{suffix}")
    dest.mkdir(parents=True, exist_ok=False)
    for rel, src in protected_paths(home).items():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            shutil.copy2(src, target)
    hashes = current_hashes(home)
    (dest / "snapshot.json").write_text(json.dumps({"created_at": utc_now().isoformat(), "reason": reason, "hashes": hashes}, indent=2) + "\n")
    manifest = load_manifest(home)
    manifest["latest_snapshot"] = str(dest)
    manifest["hashes"] = hashes
    save_manifest(home, manifest)
    snapshots = sorted(
        (path for path in root.iterdir() if path.is_dir()),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
    )
    for stale in snapshots[:-KNOWN_GOOD_SNAPSHOT_RETENTION]:
        shutil.rmtree(stale)
    log(home, f"SNAPSHOT path={dest} reason={reason}")
    return dest


def latest_snapshot(home: Path) -> Path | None:
    manifest = load_manifest(home)
    candidate = manifest.get("latest_snapshot")
    if candidate and Path(candidate).exists():
        return Path(candidate)
    root = known_good_dir(home)
    if not root.exists():
        return None
    snaps = sorted([p for p in root.iterdir() if p.is_dir()])
    return snaps[-1] if snaps else None


def restore(home: Path, snap: Path, reason: str) -> None:
    for rel, dst in protected_paths(home).items():
        src = snap / rel
        if not src.exists():
            raise FileNotFoundError(f"snapshot missing {rel}: {snap}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    if probation_path(home).exists():
        probation_path(home).unlink()
    save_manifest(home, {"latest_snapshot": str(snap), "hashes": current_hashes(home)})
    log(home, f"ROLLBACK restored={snap} reason={reason}")


def parse_config(home: Path) -> tuple[bool, str]:
    cfg = home / "config.yaml"
    if not cfg.exists():
        return False, "missing config.yaml"
    if yaml is None:
        return False, "missing pyyaml"
    try:
        yaml.safe_load(cfg.read_text())
        return True, "config_yaml_ok"
    except Exception as exc:
        return False, f"config_yaml_error={type(exc).__name__}:{exc}"


def cron_json_has_optimizer(home: Path) -> tuple[bool, str]:
    jobs_file = home / "cron" / "jobs.json"
    try:
        data = json.loads(jobs_file.read_text())
        jobs = data.get("jobs", []) if isinstance(data, dict) else data
        for job in jobs:
            if job.get("id") == OPTIMIZER_JOB_ID:
                if job.get("enabled") is True and job.get("state") != "paused":
                    return True, "optimizer_enabled"
                return False, "optimizer_not_enabled"
        return False, "optimizer_missing"
    except Exception as exc:
        return False, f"jobs_json_error={type(exc).__name__}:{exc}"


def hermes_cron_list_ok(home: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        ["hermes", "--profile", "default", "cron", "list"],
        cwd=str(home),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
        check=False,
    )
    if proc.returncode == 0:
        return True, "hermes_cron_list_ok"
    return False, "hermes_cron_list_failed=" + proc.stdout[-500:].replace("\n", " | ")


def probation_expired(home: Path, now: dt.datetime | None = None) -> tuple[bool, str]:
    path = probation_path(home)
    if not path.exists():
        return False, "no_probation"
    try:
        data = json.loads(path.read_text())
        if data.get("confirmed") is True:
            return False, "probation_confirmed"
        expiry_raw = data.get("expires_at") or data.get("expiry")
        if not expiry_raw:
            return True, "probation_missing_expiry"
        expiry = dt.datetime.fromisoformat(expiry_raw.replace("Z", "+00:00"))
        if (now or utc_now()) > expiry:
            return True, f"probation_expired change={data.get('change','unknown')}"
        return False, "probation_active"
    except Exception as exc:
        return True, f"probation_parse_error={type(exc).__name__}:{exc}"


def health(home: Path, skip_cli: bool = False) -> tuple[bool, list[str]]:
    checks = []
    ok = True
    for fn in [parse_config, cron_json_has_optimizer]:
        check_ok, msg = fn(home)
        checks.append(msg)
        ok = ok and check_ok
    if not skip_cli:
        check_ok, msg = hermes_cron_list_ok(home)
        checks.append(msg)
        ok = ok and check_ok
    expired, msg = probation_expired(home)
    checks.append(msg)
    if expired:
        ok = False
    return ok, checks


def ensure_metric_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS loop_metrics (
                id BIGSERIAL PRIMARY KEY,
                captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                run_id BIGINT NULL,
                category TEXT NOT NULL,
                metric_key TEXT NOT NULL,
                metric_value NUMERIC,
                metric_text TEXT,
                notes TEXT
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_loop_metrics_key_time ON loop_metrics(metric_key, captured_at DESC)")
    conn.commit()


def record_metrics(dsn: str, gateway_healthy: int, rollbacks: int, notes: str) -> None:
    if psycopg is None:
        return
    try:
        with psycopg.connect(dsn) as conn:
            ensure_metric_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO loop_metrics(category, metric_key, metric_value, notes) VALUES (%s,%s,%s,%s),(%s,%s,%s,%s)",
                    ("orchestration/cost", "gateway_healthy", gateway_healthy, notes, "orchestration/cost", "config_rollbacks", rollbacks, notes),
                )
            conn.commit()
    except Exception as exc:
        log(Path(os.getenv("HERMES_HOME", "/root/.hermes")), f"METRIC_WRITE_FAILED {type(exc).__name__}:{exc}")


def run(home: Path, dsn: str, skip_cli: bool = False, force_snapshot: bool = False) -> int:
    home = home.resolve()
    guardian_dir(home).mkdir(parents=True, exist_ok=True)
    hashes = current_hashes(home)
    manifest = load_manifest(home)
    have_snapshot = latest_snapshot(home) is not None
    if force_snapshot or not have_snapshot:
        snapshot(home, reason="initial" if not have_snapshot else "forced")
        manifest = load_manifest(home)
        hashes = current_hashes(home)

    changed = manifest.get("hashes") != hashes
    ok, checks = health(home, skip_cli=skip_cli)
    rollbacks = 0
    if not ok:
        snap = latest_snapshot(home)
        if snap is None:
            log(home, "UNHEALTHY no_snapshot checks=" + ";".join(checks))
            print("GUARDIAN=block no_snapshot " + ";".join(checks))
            record_metrics(dsn, 0, 0, ";".join(checks))
            return 2
        restore(home, snap, reason=";".join(checks))
        rollbacks = 1
        print(f"GUARDIAN=restored snapshot={snap} checks=" + ";".join(checks))
        record_metrics(dsn, 0, rollbacks, ";".join(checks))
        return 1

    if changed:
        snapshot(home, reason="healthy_change")
    print("GUARDIAN=ok checks=" + ";".join(checks))
    record_metrics(dsn, 1, rollbacks, ";".join(checks))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", default=os.getenv("HERMES_HOME", "/root/.hermes"))
    parser.add_argument("--dsn", default=os.getenv("WOLFY_POSTGRES_DSN", DEFAULT_DSN))
    parser.add_argument("--skip-cli", action="store_true", help="Skip hermes cron list; intended for isolated tests")
    parser.add_argument("--snapshot", action="store_true", help="Force a known-good snapshot before health checks")
    args = parser.parse_args(argv)
    return run(Path(args.home), args.dsn, skip_cli=args.skip_cli, force_snapshot=args.snapshot)


if __name__ == "__main__":
    raise SystemExit(main())
