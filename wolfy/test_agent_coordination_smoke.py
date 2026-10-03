#!/usr/bin/env python3
"""Smoke tests for Wolfy/Jonah/Sentinel Postgres run/task coordination."""
from __future__ import annotations

from wolfy_agent_coordination import (
    block_task,
    claim_next_task,
    complete_task,
    ensure_agent_task,
    finish_agent_run,
    start_agent_run,
)
from test_db import future_fixture, test_connection


def test_agent_run_rows_insert_and_finish():
    marker = future_fixture("agent-run").strategy_name
    with test_connection() as conn:
        run_id = start_agent_run(
            conn,
            agent_name="Jonah",
            role="research",
            job_id=marker,
            summary="smoke test started",
        )
        assert isinstance(run_id, int)

        finish_agent_run(
            conn,
            run_id,
            status="completed",
            summary="smoke test completed",
            records_created=1,
            input_tokens=11,
            output_tokens=7,
        )

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT agent_name, role, status, total_tokens, records_created, ended_at IS NOT NULL
                FROM agent_runs
                WHERE id = %s
                """,
                (run_id,),
            )
            row = cur.fetchone()

    assert row == ("Jonah", "research", "completed", 18, 1, True)


def test_agent_tasks_claiming_dedupes_by_fingerprint():
    fingerprint = future_fixture("agent-task").strategy_name
    with test_connection() as conn:
        first = ensure_agent_task(
            conn,
            agent_name="Jonah",
            task_type="research",
            title="Smoke research task",
            description="Prove Jonah claims before token spend.",
            source_fingerprint=fingerprint,
            topic_tags=["smoke", "dedupe"],
            priority=1,
        )
        second = ensure_agent_task(
            conn,
            agent_name="Jonah",
            task_type="research",
            title="Smoke research task duplicate",
            description="Should not create a duplicate row.",
            source_fingerprint=fingerprint,
            topic_tags=["smoke", "dedupe"],
            priority=1,
        )

        assert first.id == second.id
        assert first.created is True
        assert second.created is False

        claim = claim_next_task(
            conn,
            agent_name="Jonah",
            task_type="research",
            claim_token="smoke-token",
            source_fingerprint=fingerprint,
        )
        assert claim is not None
        assert claim.id == first.id
        assert claim.claim_token == "smoke-token"

        duplicate_claim = claim_next_task(
            conn,
            agent_name="Jonah",
            task_type="research",
            claim_token="smoke-token-2",
            source_fingerprint=fingerprint,
        )
        assert duplicate_claim is None

        complete_task(conn, claim.id, summary="smoke complete")
        with conn.cursor() as cur:
            cur.execute("SELECT status, completed_at IS NOT NULL FROM agent_tasks WHERE id = %s", (claim.id,))
            status_row = cur.fetchone()

    assert status_row == ("completed", True)


def test_agent_task_block_adds_reason_and_status():
    fingerprint = future_fixture("agent-block").strategy_name
    reason = "smoke block reason"
    with test_connection() as conn:
        task = ensure_agent_task(
            conn,
            agent_name="Sentinel",
            task_type="review",
            title="Smoke blocked task",
            description="Original description",
            source_fingerprint=fingerprint,
            priority=1,
        )
        block_task(conn, task.id, reason=reason)
        with conn.cursor() as cur:
            cur.execute("SELECT status, description FROM agent_tasks WHERE id = %s", (task.id,))
            status, description = cur.fetchone()
        # Assert the complete state transition even though the test transaction
        # is rolled back by test_connection().
        complete_task(conn, task.id, summary="cleared synthetic smoke blocked task")

    assert status == "blocked"
    assert "Original description" in description
    assert f"Blocked: {reason}" in description
