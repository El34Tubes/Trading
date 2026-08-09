from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi.testclient import TestClient


def test_dashboard_snapshot_groups_daily_progress_agents_health_recommendations_and_polls():
    from dashboard_app import build_dashboard_snapshot

    snapshot = build_dashboard_snapshot(
        now=datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc),
        tasks=[
            {"id": 1, "agent": "wolfy", "status": "completed", "title": "Recommendation writer", "updated_at": datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc)},
            {"id": 2, "agent": "mike", "status": "queued", "title": "Disk check", "updated_at": datetime(2026, 8, 6, 11, 0, tzinfo=timezone.utc)},
        ],
        runs=[
            {"agent": "yang", "status": "completed", "title": "Technical review", "started_at": datetime(2026, 8, 6, 9, 0, tzinfo=timezone.utc)},
        ],
        recommendations=[
            {"id": 9, "ticker": "MSFT", "status": "paper_candidate", "created_at": datetime(2026, 8, 6, 8, 0, tzinfo=timezone.utc), "thesis": "Approved breakout"},
        ],
        paper_trades=[],
        system_metrics=[{"category": "disk", "metric_name": "root_used_pct", "metric_value": 72.4, "captured_at": datetime(2026, 8, 6, 7, 0, tzinfo=timezone.utc)}],
        polls=[{"id": "poll-1", "question": "Approve next build?", "status": "open", "choices": ["yes", "no"]}],
        manual_notes=[{"agent": "wolfy", "note": "Watch recommendation writer", "created_at": datetime(2026, 8, 6, 6, 0, tzinfo=timezone.utc)}],
    )

    assert snapshot["refresh_seconds"] == 60
    assert "timeline" not in snapshot
    assert snapshot["current"]["as_of_date"] == "2026-08-06"
    assert snapshot["current"]["tasks"]["completed"] == 1
    assert snapshot["current"]["tasks"]["queued"] == 1
    assert snapshot["current"]["runs"]["completed"] == 1
    assert snapshot["current"]["recommendations"]["pending_attention"] == 1
    assert snapshot["agents"]["wolfy"]["completed_tasks"] == 1
    assert snapshot["agents"]["mike"]["queued_tasks"] == 1
    assert snapshot["agents"]["yang"]["completed_runs"] == 1
    assert snapshot["recommendations"]["pending_user_attention"] == 1
    assert snapshot["health"]["disk"][0]["metric_value"] == 72.4
    assert snapshot["polls"][0]["question"] == "Approve next build?"
    assert snapshot["manual_notes"][0]["note"] == "Watch recommendation writer"


def test_dashboard_requires_pin_and_exposes_summary_api():
    from dashboard_app import create_app

    app = create_app(
        repository=lambda: {
            "tasks": [],
            "runs": [],
            "recommendations": [],
            "paper_trades": [],
            "system_metrics": [],
            "polls": [],
            "manual_notes": [],
        },
        dashboard_pin="1234",
    )
    client = TestClient(app)

    assert client.get("/api/summary").status_code == 401
    ok = client.get("/api/summary", headers={"x-dashboard-pin": "1234"})
    assert ok.status_code == 200
    assert ok.json()["refresh_seconds"] == 60


def test_poll_answer_api_writes_back_and_summary_returns_answer(tmp_path):
    from dashboard_app import JsonNoteStore, create_app

    note_store = JsonNoteStore(tmp_path / "notes.json")
    app = create_app(
        repository=lambda: {
            "tasks": [],
            "runs": [],
            "recommendations": [],
            "paper_trades": [],
            "system_metrics": [],
            "polls": [{"id": "next-build", "question": "Move next?", "choices": ["paper logging"]}],
            "poll_answers": note_store.list_poll_answers(),
            "manual_notes": [],
        },
        dashboard_pin="1234",
        note_store=note_store,
    )
    client = TestClient(app)

    answer = client.post(
        "/api/polls/next-build/answer",
        headers={"x-dashboard-pin": "1234"},
        json={"choice": "paper logging", "note": "yes"},
    )

    assert answer.status_code == 200
    summary = client.get("/api/summary", headers={"x-dashboard-pin": "1234"}).json()
    assert summary["poll_answers"][0]["poll_id"] == "next-build"
    assert summary["poll_answers"][0]["choice"] == "paper logging"


def test_poll_answer_is_persisted_by_repository(tmp_path):
    from dashboard_app import JsonNoteStore

    store = JsonNoteStore(tmp_path / "notes.json")
    answer = store.add_poll_answer(poll_id="next-build", choice="paper logging", note="move forward")

    loaded = JsonNoteStore(tmp_path / "notes.json").list_poll_answers()
    assert loaded[0]["id"] == answer["id"]
    assert loaded[0]["poll_id"] == "next-build"
    assert loaded[0]["choice"] == "paper logging"


def test_manual_note_override_is_persisted_by_repository(tmp_path):
    from dashboard_app import JsonNoteStore

    store = JsonNoteStore(tmp_path / "notes.json")
    note = store.add_note(agent="wolfy", note="Pin this risk decision", status="active")

    loaded = JsonNoteStore(tmp_path / "notes.json").list_notes()
    assert loaded[0]["id"] == note["id"]
    assert loaded[0]["agent"] == "wolfy"
    assert loaded[0]["note"] == "Pin this risk decision"
