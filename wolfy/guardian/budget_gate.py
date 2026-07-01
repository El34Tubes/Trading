#!/usr/bin/env python3
"""Deterministic Wolfy LLM budget gate.

Prints one machine-readable line:
- BUDGET=ok ... and exits 0 when LLM cron work may proceed.
- BUDGET=block <reason> ... and exits non-zero when jobs should no-op.

The gate is intentionally dependency-light and supports simulation env vars for
cron/prompt dry-runs:
  WOLFY_BUDGET_SIMULATED_TOKENS_TODAY=<int>
  WOLFY_BUDGET_SIMULATED_HEADROOM_PCT=<float>
  WOLFY_BUDGET_IGNORE_AUTH=1
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
from decimal import Decimal

try:
    import psycopg
except Exception:  # pragma: no cover - surfaced at runtime
    psycopg = None

DEFAULT_DSN = "dbname=wolfy user=root host=/var/run/postgresql"
DEFAULT_DAILY_CAP = 200_000
DEFAULT_BLOCK_HEADROOM_PCT = 15.0


def env_int(name: str, default: int | None = None) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def env_float(name: str, default: float | None = None) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return float(raw)


def ensure_loop_metrics(conn) -> None:
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
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_loop_metrics_key_time "
            "ON loop_metrics(metric_key, captured_at DESC)"
        )
    conn.commit()


def record_metric(conn, key: str, value: float | int | None, text: str | None = None, notes: str | None = None) -> None:
    ensure_loop_metrics(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO loop_metrics(category, metric_key, metric_value, metric_text, notes)
            VALUES ('orchestration/cost', %s, %s, %s, %s)
            """,
            (key, value, text, notes),
        )
    conn.commit()


def tokens_today(conn) -> int:
    simulated = env_int("WOLFY_BUDGET_SIMULATED_TOKENS_TODAY")
    if simulated is not None:
        return simulated
    with conn.cursor() as cur:
        # agent_runs has evolved; introspect token columns defensively.
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'agent_runs'
            """
        )
        cols = {r[0] for r in cur.fetchall()}
        if not {"input_tokens", "output_tokens"}.issubset(cols):
            return 0
        ts_col = "started_at" if "started_at" in cols else "created_at" if "created_at" in cols else None
        if ts_col is None:
            cur.execute("SELECT COALESCE(SUM(COALESCE(input_tokens,0)+COALESCE(output_tokens,0)),0) FROM agent_runs")
        else:
            cur.execute(
                f"""
                SELECT COALESCE(SUM(COALESCE(input_tokens,0)+COALESCE(output_tokens,0)),0)
                FROM agent_runs
                WHERE {ts_col} >= date_trunc('day', now() AT TIME ZONE 'America/New_York') AT TIME ZONE 'America/New_York'
                """
            )
        value = cur.fetchone()[0] or 0
        return int(value)


def latest_usage_snapshot_text(conn) -> str:
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT to_jsonb(t)::text
                FROM agent_usage_snapshots t
                ORDER BY 1 DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
            return row[0] if row else "none"
    except Exception as exc:
        return f"unavailable:{type(exc).__name__}"


def auth_status() -> str:
    if os.getenv("WOLFY_BUDGET_IGNORE_AUTH") == "1":
        return "ignored"
    try:
        proc = subprocess.run(
            ["hermes", "auth", "list", "openai-codex"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
            check=False,
        )
        return proc.stdout.strip().replace("\n", " | ") or f"exit={proc.returncode}"
    except Exception as exc:
        return f"unavailable:{type(exc).__name__}:{exc}"


def decide(tokens: int, cap: int, auth: str, block_headroom_pct: float) -> tuple[bool, str, float]:
    simulated_headroom = env_float("WOLFY_BUDGET_SIMULATED_HEADROOM_PCT")
    headroom_pct = simulated_headroom if simulated_headroom is not None else max(0.0, (cap - tokens) * 100.0 / cap)
    if "usage_limit_reached" in auth or "rate-limited" in auth or "HTTP 429" in auth:
        return False, "codex_usage_limited", headroom_pct
    if tokens >= cap:
        return False, f"token_cap_exceeded tokens_today={tokens} cap={cap}", headroom_pct
    if headroom_pct < block_headroom_pct:
        return False, f"low_headroom_pct={headroom_pct:.2f} threshold={block_headroom_pct:.2f}", headroom_pct
    return True, f"tokens_today={tokens} cap={cap} headroom_pct={headroom_pct:.2f}", headroom_pct


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=os.getenv("WOLFY_POSTGRES_DSN", DEFAULT_DSN))
    parser.add_argument("--daily-cap", type=int, default=env_int("WOLFY_BUDGET_DAILY_TOKEN_CAP", DEFAULT_DAILY_CAP))
    parser.add_argument("--block-headroom-pct", type=float, default=env_float("WOLFY_BUDGET_BLOCK_HEADROOM_PCT", DEFAULT_BLOCK_HEADROOM_PCT))
    parser.add_argument("--no-record", action="store_true")
    args = parser.parse_args(argv)

    if psycopg is None:
        print("BUDGET=block missing_psycopg")
        return 2
    try:
        with psycopg.connect(args.dsn) as conn:
            token_count = tokens_today(conn)
            usage_text = latest_usage_snapshot_text(conn)
            auth = auth_status()
            ok, reason, headroom_pct = decide(token_count, args.daily_cap, auth, args.block_headroom_pct)
            if not args.no_record:
                record_metric(conn, "usage_headroom_pct", headroom_pct, notes=f"auth={auth[:200]} usage={usage_text[:300]}")
                record_metric(conn, "tokens_today", token_count, notes="budget_gate")
            if ok:
                print(f"BUDGET=ok {reason}")
                return 0
            print(f"BUDGET=block {reason}")
            return 1
    except Exception as exc:
        print(f"BUDGET=block gate_error={type(exc).__name__}:{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
