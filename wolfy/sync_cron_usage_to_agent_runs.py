#!/usr/bin/env python3
"""Sync Hermes cron session token/accounting metadata into Wolfy's Postgres agent_runs.

This is best-effort accounting: Hermes state.db has real per-session token
counters, while cron job names live in `hermes cron list --all`. We join those
sources by the cron session id pattern `cron_<job_id>_<timestamp>` and upsert a
cron-session ledger row in agent_runs. No market logic lives here.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from typing import Iterable

import psycopg

DEFAULT_STATE_DB = Path("/root/.hermes/state.db")
DEFAULT_PG_DSN = "dbname=wolfy user=root host=/var/run/postgresql"
CRON_SESSION_RE = re.compile(r"^cron_([0-9a-f]{12})_\d{8}_\d{6}$")


@dataclass(frozen=True)
class CronJob:
    job_id: str
    name: str
    profile: str | None = None


@dataclass(frozen=True)
class CronSession:
    session_id: str
    cron_job_id: str
    started_at: datetime
    ended_at: datetime | None
    end_reason: str | None
    message_count: int
    tool_call_count: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    reasoning_tokens: int
    estimated_cost_usd: float | None

    @property
    def total_tokens(self) -> int:
        return (self.input_tokens or 0) + (self.output_tokens or 0)


def parse_cron_jobs(text: str) -> dict[str, CronJob]:
    jobs: dict[str, CronJob] = {}
    current_id: str | None = None
    current_name: str | None = None
    current_profile: str | None = None
    for line in text.splitlines():
        m = re.match(r"\s*([0-9a-f]{12}) \[[^]]+\]", line)
        if m:
            if current_id and current_name:
                jobs[current_id] = CronJob(current_id, current_name, current_profile)
            current_id = m.group(1)
            current_name = None
            current_profile = None
            continue
        if current_id:
            name_match = re.match(r"\s*Name:\s+(.*\S)\s*$", line)
            if name_match:
                current_name = name_match.group(1)
                continue
            profile_match = re.match(r"\s*Profile:\s+(.*\S)\s*$", line)
            if profile_match:
                current_profile = profile_match.group(1)
                continue
    if current_id and current_name:
        jobs[current_id] = CronJob(current_id, current_name, current_profile)
    return jobs


def load_cron_jobs() -> dict[str, CronJob]:
    try:
        out = subprocess.check_output(
            ["hermes", "--profile", "default", "cron", "list", "--all"],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
    except Exception as exc:
        print(f"warning: could not read cron list: {type(exc).__name__}: {exc}", file=sys.stderr)
        return {}
    return parse_cron_jobs(out)


def infer_agent_and_role(job: CronJob | None, cron_job_id: str) -> tuple[str, str, str]:
    name = job.name if job else f"unknown cron job {cron_job_id}"
    lowered = name.lower()
    if "jonah" in lowered:
        agent = "Jonah"
        role = "research"
    elif "sentinel" in lowered:
        agent = "Sentinel"
        role = "review"
    elif "yang" in lowered:
        agent = "Yang"
        role = "technical_analysis"
    elif "clerky" in lowered:
        agent = "Clerky"
        role = "admin_reporting"
    elif "mike" in lowered:
        agent = "Mike"
        role = "operations"
    elif "wolfy" in lowered:
        agent = "Wolfy"
        role = "analysis"
    else:
        agent = "WolfyOps"
        role = "cron"
    return agent, role, name


def dt_from_unix(value: float | int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


def iter_cron_sessions(state_db: Path, since_days: int) -> Iterable[CronSession]:
    cutoff = datetime.now(timezone.utc).timestamp() - since_days * 86400
    con = sqlite3.connect(state_db)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            SELECT id, started_at, ended_at, end_reason, message_count, tool_call_count,
                   input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
                   reasoning_tokens, estimated_cost_usd
            FROM sessions
            WHERE source='cron' AND started_at >= ?
            ORDER BY started_at ASC
            """,
            (cutoff,),
        ).fetchall()
    finally:
        con.close()
    for row in rows:
        match = CRON_SESSION_RE.match(row["id"])
        if not match:
            continue
        started = dt_from_unix(row["started_at"])
        if started is None:
            continue
        yield CronSession(
            session_id=row["id"],
            cron_job_id=match.group(1),
            started_at=started,
            ended_at=dt_from_unix(row["ended_at"]),
            end_reason=row["end_reason"],
            message_count=int(row["message_count"] or 0),
            tool_call_count=int(row["tool_call_count"] or 0),
            input_tokens=int(row["input_tokens"] or 0),
            output_tokens=int(row["output_tokens"] or 0),
            cache_read_tokens=int(row["cache_read_tokens"] or 0),
            cache_write_tokens=int(row["cache_write_tokens"] or 0),
            reasoning_tokens=int(row["reasoning_tokens"] or 0),
            estimated_cost_usd=row["estimated_cost_usd"],
        )


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS session_id TEXT")
        cur.execute("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS cron_job_id TEXT")
        cur.execute("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS source TEXT")
        cur.execute("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS message_count INTEGER")
        cur.execute("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS tool_call_count INTEGER")
        cur.execute("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS cache_read_tokens BIGINT")
        cur.execute("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS cache_write_tokens BIGINT")
        cur.execute("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS reasoning_tokens BIGINT")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_runs_session_id ON agent_runs(session_id) WHERE session_id IS NOT NULL")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_cron_job_started ON agent_runs(cron_job_id, started_at DESC) WHERE cron_job_id IS NOT NULL")


def upsert_sessions(conn, sessions: Iterable[CronSession], jobs: dict[str, CronJob]) -> tuple[int, int]:
    inserted = 0
    updated = 0
    with conn.cursor() as cur:
        for session in sessions:
            job = jobs.get(session.cron_job_id)
            agent, role, job_name = infer_agent_and_role(job, session.cron_job_id)
            if session.ended_at is None:
                status = "started"
            elif session.total_tokens == 0 and agent not in {"Mike", "Clerky"}:
                status = "blocked"
            else:
                status = "completed"
            summary = f"Cron session usage sync: {job_name}"
            error_message = None
            if status == "blocked":
                error_message = "No token counters recorded; likely provider/usage-limit failure or startup failure. Check Hermes cron logs."
            cur.execute(
                """
                INSERT INTO agent_runs(
                    agent_name, role, job_id, started_at, ended_at, status,
                    input_tokens, output_tokens, total_tokens, estimated_cost,
                    summary, error_message, session_id, cron_job_id, source,
                    message_count, tool_call_count, cache_read_tokens,
                    cache_write_tokens, reasoning_tokens
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (session_id) WHERE session_id IS NOT NULL DO UPDATE SET
                    agent_name=EXCLUDED.agent_name,
                    role=EXCLUDED.role,
                    job_id=EXCLUDED.job_id,
                    ended_at=EXCLUDED.ended_at,
                    status=EXCLUDED.status,
                    input_tokens=EXCLUDED.input_tokens,
                    output_tokens=EXCLUDED.output_tokens,
                    total_tokens=EXCLUDED.total_tokens,
                    estimated_cost=EXCLUDED.estimated_cost,
                    summary=EXCLUDED.summary,
                    error_message=EXCLUDED.error_message,
                    cron_job_id=EXCLUDED.cron_job_id,
                    source=EXCLUDED.source,
                    message_count=EXCLUDED.message_count,
                    tool_call_count=EXCLUDED.tool_call_count,
                    cache_read_tokens=EXCLUDED.cache_read_tokens,
                    cache_write_tokens=EXCLUDED.cache_write_tokens,
                    reasoning_tokens=EXCLUDED.reasoning_tokens
                RETURNING (xmax = 0) AS inserted
                """,
                (
                    agent, role, f"cron:{session.cron_job_id}", session.started_at,
                    session.ended_at, status, session.input_tokens, session.output_tokens,
                    session.total_tokens, session.estimated_cost_usd, summary, error_message,
                    session.session_id, session.cron_job_id, "cron", session.message_count,
                    session.tool_call_count, session.cache_read_tokens, session.cache_write_tokens,
                    session.reasoning_tokens,
                ),
            )
            was_inserted = bool(cur.fetchone()[0])
            if was_inserted:
                inserted += 1
            else:
                updated += 1
    return inserted, updated


def print_daily_summary(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT agent_name,
                   count(*) AS runs,
                   count(*) FILTER (WHERE status='blocked') AS blocked,
                   COALESCE(sum(input_tokens),0) AS input_tokens,
                   COALESCE(sum(output_tokens),0) AS output_tokens,
                   COALESCE(sum(total_tokens),0) AS total_tokens
            FROM agent_runs
            WHERE source='cron' AND started_at >= now() - interval '1 day'
            GROUP BY agent_name
            ORDER BY total_tokens DESC, agent_name
            """
        )
        rows = cur.fetchall()
    if not rows:
        print("No cron agent usage rows in the last day.")
        return
    print("Last-24h cron usage by agent:")
    for agent, runs, blocked, inp, out, total in rows:
        print(f"- {agent}: runs={runs} blocked={blocked} input={inp} output={out} total={total}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-db", type=Path, default=DEFAULT_STATE_DB)
    parser.add_argument("--pg-dsn", default=DEFAULT_PG_DSN)
    parser.add_argument("--since-days", type=int, default=2)
    parser.add_argument("--summary", action="store_true", help="Print last-24h per-agent usage summary")
    args = parser.parse_args()

    if not args.state_db.exists():
        print(f"state db not found: {args.state_db}", file=sys.stderr)
        return 2
    jobs = load_cron_jobs()
    sessions = list(iter_cron_sessions(args.state_db, args.since_days))
    with psycopg.connect(args.pg_dsn) as conn:
        ensure_schema(conn)
        inserted, updated = upsert_sessions(conn, sessions, jobs)
        if args.summary:
            print_daily_summary(conn)
    if inserted or updated:
        print(f"Synced cron usage to agent_runs: inserted={inserted} updated={updated} sessions_seen={len(sessions)} jobs_known={len(jobs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
