from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


SNAPSHOT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SNAPSHOT_SHA = "b" * 64


def _artifact(tmp_path: Path, **overrides) -> Path:
    payload = {
        "schema_version": "wolfy-mid-small-production-release-v1",
        "enabled": True,
        "database": "wolfy",
        "config_version": "mid-small-paper-canary-v1",
        "strategy": "close_confirmed_breakout",
        "strategy_id": "liquid_rs_breakout_close_confirm_1r",
        "strategy_version": "approved-2026-08-03",
        "policy_version": "mid_small_multi_strategy_pivot_v1",
        "snapshot_id": SNAPSHOT_ID,
        "snapshot_fingerprint": SNAPSHOT_SHA,
        "signal_dt": "2099-05-01",
        "publisher_count": 1,
        "account_equity": "100000",
        "stock_fallback_enabled": True,
        "paper_only": True,
        "no_live_execution": True,
        "broker_execution_enabled": False,
        "external_delivery_enabled": False,
        "previous_publisher": "wolfy-approved-breakout-paper",
        "canary_evidence_path": str(tmp_path / "canary.json"),
        "rollback_state_path": str(tmp_path / "state.json"),
    }
    binding = {
        key: payload[key]
        for key in (
            "config_version", "database", "policy_version", "signal_dt", "snapshot_fingerprint",
            "snapshot_id", "strategy", "strategy_id", "strategy_version",
        )
    }
    payload["scope_fingerprint"] = hashlib.sha256(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    payload.update(overrides)
    path = tmp_path / "release.json"
    path.write_text(json.dumps(payload, sort_keys=True) + "\n")
    return path


def test_checked_in_release_artifact_is_durably_disabled():
    from production_release import DEFAULT_RELEASE_ARTIFACT, load_release_artifact

    artifact = load_release_artifact(DEFAULT_RELEASE_ARTIFACT, require_enabled=False)
    assert artifact.enabled is False
    with pytest.raises(Exception, match="disabled"):
        load_release_artifact(DEFAULT_RELEASE_ARTIFACT, require_enabled=True)


def test_release_artifact_refuses_nonproduction_database_and_research_sleeve(tmp_path):
    from production_release import ProductionReleaseError, load_release_artifact

    with pytest.raises(ProductionReleaseError, match="database wolfy"):
        load_release_artifact(_artifact(tmp_path, database="wolfy_test"))
    with pytest.raises(ProductionReleaseError, match="close_confirmed_breakout"):
        load_release_artifact(_artifact(tmp_path, strategy="trend_pullback_reclaim"))


def test_release_artifact_binds_exact_snapshot_and_fixed_safety_policy(tmp_path):
    from production_release import ProductionReleaseError, load_release_artifact

    release = load_release_artifact(_artifact(tmp_path))
    assert release.snapshot_id == SNAPSHOT_ID
    assert release.snapshot_fingerprint == SNAPSHOT_SHA
    assert release.risk_fraction == "0.05"
    assert release.maximum_positions == 20
    assert release.maximum_positions_per_sector == 5
    assert release.broker_execution_enabled is False
    assert release.external_delivery_enabled is False

    with pytest.raises(ProductionReleaseError, match="snapshot_fingerprint"):
        load_release_artifact(_artifact(tmp_path, snapshot_fingerprint="c" * 64))
    with pytest.raises(ProductionReleaseError, match="broker"):
        load_release_artifact(_artifact(tmp_path, broker_execution_enabled=True))


def test_validate_production_connection_requires_exact_local_wolfy():
    from production_release import ProductionReleaseError, validate_production_connection

    class Info:
        host = "/var/run/postgresql"
        user = "root"
        dbname = "wolfy_test"

    class Conn:
        info = Info()

        def execute(self, _sql, _params=None):
            return self

        def fetchone(self):
            return ("wolfy_test",)

    with pytest.raises(ProductionReleaseError, match="exact production database wolfy"):
        validate_production_connection(Conn())


def test_snapshot_preflight_requires_source_verified_us_issuer_and_exact_binding(tmp_path):
    from production_release import ProductionReleaseError, load_release_artifact, verify_snapshot_preflight

    release = load_release_artifact(_artifact(tmp_path))

    class Result:
        def __init__(self, row):
            self.row = row
        def fetchone(self):
            return self.row

    class Conn:
        def __init__(self, rows):
            self.rows = iter(rows)
        def execute(self, _sql, _params=None):
            return Result(next(self.rows))

    good = Conn([
        (SNAPSHOT_ID, release.signal_dt, release.policy_version, SNAPSHOT_SHA, 2),
        (2, 0),
    ])
    assert verify_snapshot_preflight(good, release) == 2

    bad = Conn([
        (SNAPSHOT_ID, release.signal_dt, release.policy_version, SNAPSHOT_SHA, 2),
        (2, 1),
    ])
    with pytest.raises(ProductionReleaseError, match="source-verified issuer country"):
        verify_snapshot_preflight(bad, release)


def _publication(ids, *, created):
    return {
        "recommendation_ids": ids,
        "decision": "actionable" if ids else "no_trade",
        "recommendations_created": created,
        "positions_total": len(ids),
        "maximum_sector_positions": min(len(ids), 5),
        "risk_fractions": ["0.05"] * len(ids),
        "aggregate_risk": str(len(ids) * 0.05),
        "research_only_published": 0,
        "exact_chain_or_stock_fallback": True,
        "paper_only": True,
        "no_live_execution": True,
        "broker_orders_created": 0,
        "external_deliveries": 0,
    }


def test_canary_enforces_caps_broker_zero_and_idempotent_rerun(tmp_path):
    from production_release import execute_canary_callbacks, load_release_artifact

    release = load_release_artifact(_artifact(tmp_path))
    ids = [f"00000000-0000-4000-8000-{i:012d}" for i in range(1, 21)]
    calls = []

    def publish(*, rerun):
        calls.append(rerun)
        return _publication(ids, created=0 if rerun else 20)

    result = execute_canary_callbacks(release, publish=publish, readback=lambda: _publication(ids, created=0))
    assert calls == [False, True]
    assert result["passed"] is True
    assert result["idempotent_rerun"] is True
    assert result["broker_orders_created"] == 0


def test_canary_fails_closed_on_caps_or_broker_activity(tmp_path):
    from production_release import ProductionReleaseError, execute_canary_callbacks, load_release_artifact

    release = load_release_artifact(_artifact(tmp_path))
    unsafe = _publication(["00000000-0000-4000-8000-000000000001"], created=1)
    unsafe["broker_orders_created"] = 1
    with pytest.raises(ProductionReleaseError, match="broker_orders_created"):
        execute_canary_callbacks(release, publish=lambda **_k: unsafe, readback=lambda: unsafe)


def test_canary_accepts_fully_evaluated_deterministic_no_trade(tmp_path):
    from production_release import execute_canary_callbacks, load_release_artifact

    release = load_release_artifact(_artifact(tmp_path))
    empty = _publication([], created=0)
    result = execute_canary_callbacks(
        release, publish=lambda **_k: dict(empty), readback=lambda: dict(empty)
    )
    assert result["passed"] is True
    assert result["decision"] == "no_trade"
    assert result["recommendation_ids"] == []


def test_scheduled_callbacks_accept_authorized_zero_create_rerun(tmp_path):
    from production_release import execute_scheduled_callbacks, load_release_artifact

    release = load_release_artifact(_artifact(tmp_path))
    ids = ["00000000-0000-4000-8000-000000000001"]
    calls = []

    def publish(*, rerun):
        calls.append(rerun)
        return _publication(ids, created=0)

    result = execute_scheduled_callbacks(
        release,
        publish=publish,
        readback=lambda: _publication(ids, created=0),
        canary_evidence={"recommendation_ids": ids},
    )
    assert calls == [True]
    assert result["passed"] is True
    assert result["scheduled"] is True
    assert result["recommendations_created"] == 0
    assert result["recommendation_ids"] == ids


def test_scheduled_callbacks_reject_post_canary_creation(tmp_path):
    from production_release import ProductionReleaseError, execute_scheduled_callbacks, load_release_artifact

    release = load_release_artifact(_artifact(tmp_path))
    ids = ["00000000-0000-4000-8000-000000000001"]
    with pytest.raises(ProductionReleaseError, match="created recommendations after canary"):
        execute_scheduled_callbacks(
            release,
            publish=lambda **_kwargs: _publication(ids, created=1),
            readback=lambda: _publication(ids, created=0),
            canary_evidence={"recommendation_ids": ids},
        )


def test_source_cache_is_strictly_validated_without_absolute_path_dependency(tmp_path):
    from production_release import ProductionReleaseError, load_source_cache

    payload = {
        "fetched_at": "2099-05-02T01:02:03.123456789Z",
        "massive": {
            "page_count": 1,
            "page_sha256": ["a" * 64],
            "row_count": 1,
            "rows": [{
                "ticker": "ACME", "type": "CS", "locale": "us", "market": "stocks",
                "primary_exchange": "XNAS", "currency_name": "usd", "active": True,
            }],
            "source_url": "https://example.test/massive",
        },
        "nasdaq": {
            "payload_sha256": "b" * 64,
            "row_count": 1,
            "rows": [{
                "symbol": "ACME", "country": "United States", "marketCap": "1000000000",
                "sector": "Industrials",
            }],
            "source_url": "https://example.test/nasdaq",
        },
    }
    path = tmp_path / "bulk.json"
    path.write_text(json.dumps(payload))
    loaded = load_source_cache(path)
    assert tuple(loaded.massive_rows) == ("ACME",)
    assert loaded.fetched_at.microsecond == 123456

    payload["nasdaq"]["row_count"] = 2
    path.write_text(json.dumps(payload))
    with pytest.raises(ProductionReleaseError, match="row_count"):
        load_source_cache(path)


def test_rollback_is_one_command_non_destructive_and_blocks_scheduled_mode(tmp_path):
    from production_release import (
        ProductionReleaseError,
        authorize_scheduled_production,
        load_release_artifact,
        rollback_release,
    )

    release_path = _artifact(tmp_path)
    release = load_release_artifact(release_path)
    evidence = {
        "schema_version": "wolfy-mid-small-canary-evidence-v1",
        "passed": True,
        "artifact_sha256": hashlib.sha256(release_path.read_bytes()).hexdigest(),
        "snapshot_id": release.snapshot_id,
        "snapshot_fingerprint": release.snapshot_fingerprint,
        "config_version": release.config_version,
        "publisher_count": 1,
        "broker_orders_created": 0,
        "external_deliveries": 0,
    }
    Path(release.canary_evidence_path).write_text(json.dumps(evidence))
    assert authorize_scheduled_production(release, release_path)["authorized"] is True

    state = rollback_release(release, release_path)
    assert state["enabled"] is False
    assert state["rows_deleted"] == 0
    assert state["previous_publisher_restored"] is True
    with pytest.raises(ProductionReleaseError, match="rolled back"):
        authorize_scheduled_production(release, release_path)
