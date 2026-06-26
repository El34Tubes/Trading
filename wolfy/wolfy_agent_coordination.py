#!/usr/bin/env python3
"""Postgres coordination helpers for the Wolfy/Jonah/Sentinel agent desk.

SQLite is still Wolfy's live research source of truth. This module makes the
Postgres oversight layer operational by giving scripts a small, audited API for:

- recording every agent run in agent_runs;
- creating/deduping work in agent_tasks;
- claiming tasks before an LLM spends tokens;
- marking work completed or blocked.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
import uuid
from typing import Iterable, Optional

from wolfy_db import DEFAULT_POSTGRES_DSN, DatabaseConfig, connect_postgres

DEFAULT_PG_DSN = os.environ.get("WOLFY_POSTGRES_DSN") or os.environ.get("WOLFY_PG_DSN") or DEFAULT_POSTGRES_DSN


@dataclass(frozen=True)
class AgentTask:
    id: int
    agent_name: str
    task_type: str
    title: str
    status: str
    claim_token: Optional[str]
    source_fingerprint: Optional[str]
    created: bool = False


@dataclass(frozen=True)
class ClaimResult:
    id: int
    agent_name: str
    task_type: str
    title: str
    status: str
    claim_token: str
    source_fingerprint: Optional[str]


def connect(dsn: str = DEFAULT_PG_DSN):
    """Return a psycopg connection to Wolfy's Postgres database."""
    return connect_postgres(DatabaseConfig(postgres_dsn=dsn))


def stable_fingerprint(*parts: object) -> str:
    """Create a stable sha256 fingerprint for deduping source-backed work."""
    h = hashlib.sha256()
    for part in parts:
        h.update(str(part or "").encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def new_claim_token(agent_name: str) -> str:
    return f"{agent_name.lower()}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:12]}"


def _list_or_empty(values: Optional[Iterable[str]]) -> list[str]:
    if not values:
        return []
    return [str(v).strip().upper() if len(str(v).strip()) <= 5 and str(v).strip().isalpha() else str(v).strip() for v in values if str(v).strip()]


def ensure_coordination_schema(conn) -> None:
    """Install non-destructive indexes needed for task dedupe/claiming."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_tasks_dedupe_fingerprint
            ON agent_tasks(agent_name, task_type, source_fingerprint)
            WHERE source_fingerprint IS NOT NULL
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_agent_tasks_claimable
            ON agent_tasks(agent_name, task_type, priority, created_at)
            WHERE status = 'queued'
            """
        )


def ensure_agent_task(
    conn,
    *,
    agent_name: str,
    task_type: str,
    title: str,
    description: str | None = None,
    source_fingerprint: str | None = None,
    topic_tags: Optional[Iterable[str]] = None,
    ticker_symbols: Optional[Iterable[str]] = None,
    priority: int = 50,
) -> AgentTask:
    """Create a queued agent task unless an equivalent fingerprint already exists.

    Deduplication scope is (agent_name, task_type, source_fingerprint). Existing
    completed or in-progress tasks are returned rather than duplicated, which is
    the key guard against Jonah re-spending tokens on the same research source.
    """
    ensure_coordination_schema(conn)
    tags = _list_or_empty(topic_tags)
    tickers = _list_or_empty(ticker_symbols)
    with conn.cursor() as cur:
        if source_fingerprint:
            cur.execute(
                """
                INSERT INTO agent_tasks
                  (agent_name, task_type, title, description, status, priority,
                   source_fingerprint, topic_tags, ticker_symbols)
                VALUES (%s,%s,%s,%s,'queued',%s,%s,%s,%s)
                ON CONFLICT (agent_name, task_type, source_fingerprint)
                  WHERE source_fingerprint IS NOT NULL
                DO NOTHING
                RETURNING id, agent_name, task_type, title, status, claim_token, source_fingerprint
                """,
                (agent_name, task_type, title, description, priority, source_fingerprint, tags, tickers),
            )
            row = cur.fetchone()
            if row is not None:
                return AgentTask(*row, created=True)
            cur.execute(
                """
                SELECT id, agent_name, task_type, title, status, claim_token, source_fingerprint
                FROM agent_tasks
                WHERE agent_name=%s AND task_type=%s AND source_fingerprint=%s
                ORDER BY id
                LIMIT 1
                """,
                (agent_name, task_type, source_fingerprint),
            )
            row = cur.fetchone()
            if row is None:  # pragma: no cover - defensive against concurrent DDL oddities
                raise RuntimeError("deduped agent_task disappeared before it could be read")
            return AgentTask(*row, created=False)

        cur.execute(
            """
            INSERT INTO agent_tasks
              (agent_name, task_type, title, description, status, priority,
               source_fingerprint, topic_tags, ticker_symbols)
            VALUES (%s,%s,%s,%s,'queued',%s,%s,%s,%s)
            RETURNING id, agent_name, task_type, title, status, claim_token, source_fingerprint
            """,
            (agent_name, task_type, title, description, priority, source_fingerprint, tags, tickers),
        )
        return AgentTask(*cur.fetchone(), created=True)


def claim_next_task(
    conn,
    *,
    agent_name: str,
    task_type: str | None = None,
    claim_token: str | None = None,
    source_fingerprint: str | None = None,
) -> ClaimResult | None:
    """Atomically claim the next queued task with SELECT FOR UPDATE SKIP LOCKED."""
    ensure_coordination_schema(conn)
    token = claim_token or new_claim_token(agent_name)
    filters = ["agent_name = %s", "status = 'queued'"]
    params: list[object] = [agent_name]
    if task_type is not None:
        filters.append("task_type = %s")
        params.append(task_type)
    if source_fingerprint is not None:
        filters.append("source_fingerprint = %s")
        params.append(source_fingerprint)
    where = " AND ".join(filters)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH next_task AS (
                SELECT id
                FROM agent_tasks
                WHERE {where}
                ORDER BY priority ASC, created_at ASC, id ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE agent_tasks t
            SET status='in_progress', claim_token=%s, claimed_at=now(), updated_at=now()
            FROM next_task
            WHERE t.id = next_task.id
            RETURNING t.id, t.agent_name, t.task_type, t.title, t.status, t.claim_token, t.source_fingerprint
            """,
            (*params, token),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return ClaimResult(*row)


def complete_task(conn, task_id: int, *, summary: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_tasks
            SET status='completed', completed_at=now(), updated_at=now(), description=COALESCE(%s, description)
            WHERE id=%s
            """,
            (summary, task_id),
        )


def block_task(conn, task_id: int, *, reason: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_tasks
            SET status='blocked', updated_at=now(),
                description=concat_ws(E'\n', description, %s::text),
                error_message=COALESCE(error_message, %s::text)
            WHERE id=%s
            """,
            (f"Blocked: {reason}", reason, task_id),
        )


def start_agent_run(
    conn,
    *,
    agent_name: str,
    role: str,
    job_id: str | None = None,
    task_id: int | None = None,
    status: str = "started",
    summary: str | None = None,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_runs(agent_name, role, job_id, task_id, status, summary)
            VALUES (%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (agent_name, role, job_id, task_id, status, summary),
        )
        return int(cur.fetchone()[0])


def finish_agent_run(
    conn,
    run_id: int,
    *,
    status: str,
    summary: str | None = None,
    error_message: str | None = None,
    records_created: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    estimated_cost: float | None = None,
) -> None:
    total_tokens = None
    if input_tokens is not None or output_tokens is not None:
        total_tokens = (input_tokens or 0) + (output_tokens or 0)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_runs
            SET ended_at=now(), status=%s, summary=COALESCE(%s, summary),
                error_message=%s, records_created=COALESCE(%s, records_created),
                input_tokens=COALESCE(%s, input_tokens), output_tokens=COALESCE(%s, output_tokens),
                total_tokens=COALESCE(%s, total_tokens), estimated_cost=COALESCE(%s, estimated_cost)
            WHERE id=%s
            """,
            (status, summary, error_message, records_created, input_tokens, output_tokens, total_tokens, estimated_cost, run_id),
        )
