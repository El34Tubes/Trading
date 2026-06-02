#!/usr/bin/env python3
"""Deterministic context pre-run for Clerky's four-hour Wolfy activity ledger.

Keeps the Clerky LLM from spending tokens rediscovering schemas or issuing
fragile ad-hoc SQL against the Kanban/agent ledgers.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path('/root/.hermes')
KANBAN_DB = ROOT / 'kanban' / 'boards' / 'wolfy' / 'kanban.db'
WOLFY_DB = ROOT / 'wolfy' / 'wolfy.db'
STATE_DB = ROOT / 'state.db'
CRON_OUTPUT = ROOT / 'cron' / 'output'
CLERKY_JOB = 'a739dac0d264'


def et(ts: int | float | None) -> str:
    if not ts:
        return ''
    return dt.datetime.fromtimestamp(float(ts), dt.timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M %Z')


def heading(name: str) -> None:
    print(f'\n## {name}')


def rows(db: Path, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        return list(con.execute(sql, params))
    finally:
        con.close()


def scalar(db: Path, sql: str, params: tuple = (), default=0):
    try:
        r = rows(db, sql, params)
        if not r:
            return default
        return r[0][0]
    except Exception:
        return default


def run(cmd: list[str], timeout: int = 60) -> str:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT, timeout=timeout).strip()
    except Exception as exc:
        return f'ERROR: {type(exc).__name__}: {exc}'


def previous_ledger_start() -> float:
    outdir = CRON_OUTPUT / CLERKY_JOB
    files = sorted(outdir.glob('*.md'), key=lambda p: p.stat().st_mtime, reverse=True)
    # The current cron output is not written yet during pre-run, so latest completed ledger is OK.
    if files:
        return files[0].stat().st_mtime
    return (dt.datetime.now().timestamp() - 4 * 3600)


def main() -> int:
    now = dt.datetime.now().astimezone()
    since = previous_ledger_start()
    print('CLERKY_ACTIVITY_CONTEXT')
    print(f'generated_at={now.isoformat(timespec="seconds")}')
    print(f'since={et(since)}')
    print('HERMES-EOD CONSTITUTION: EOD ONLY; no intraday actionable recommendations; no auto-execution; LLM interprets deterministic signals only; separate FACT vs JUDGMENT.')
    print('Instructions: use this script output as the factual source; do not re-query schemas unless investigating an anomaly. Clerky is administrative only: do not make market analysis, trade recommendations, numeric edge claims, or execution suggestions.')

    heading('cron_status')
    cron = run(['hermes', '--profile', 'default', 'cron', 'list', '--all'], timeout=90)
    # Keep only job summary lines to avoid flooding the LLM.
    for line in cron.splitlines():
        if any(key in line for key in ('Name:', 'Next run:', 'Last run:', 'Script:', 'Mode:', '[active]', '[paused]')):
            print(line)

    heading('kanban_counts')
    if KANBAN_DB.exists():
        for r in rows(KANBAN_DB, 'SELECT status, count(*) AS n FROM tasks GROUP BY status ORDER BY status'):
            print(f'{r["status"]}\t{r["n"]}')
        print('recent_events_since_prior_ledger')
        for r in rows(KANBAN_DB, '''
            SELECT e.created_at, e.task_id, t.title, e.kind, e.payload
            FROM task_events e LEFT JOIN tasks t ON t.id=e.task_id
            WHERE e.created_at >= ?
            ORDER BY e.created_at DESC
            LIMIT 20
        ''', (since,)):
            payload = (r['payload'] or '').replace('\n', ' ')[:220]
            print(f'{et(r["created_at"])}\t{r["task_id"]}\t{r["kind"]}\t{r["title"]}\t{payload}')
        print('open_tasks')
        for r in rows(KANBAN_DB, '''
            SELECT id, status, assignee, title
            FROM tasks
            WHERE status NOT IN ('done','completed')
            ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'todo' THEN 1 WHEN 'blocked' THEN 2 ELSE 3 END, created_at
            LIMIT 20
        '''):
            print(f'{r["id"]}\t{r["status"]}\t{r["assignee"]}\t{r["title"]}')
    else:
        print(f'MISSING {KANBAN_DB}')

    heading('sqlite_wolfy_counts')
    for table in ['knowledge_notes','knowledge_sources','strategy_rules','reports','recommendations','paper_trades','recommendation_outcomes','scanner_runs','scanner_results','alpha_search_reports','alpha_leads','alpha_handoffs','insider_leads','suspicious_activity_flags','yang_reviews','system_metrics']:
        print(f'{table}\t{scalar(WOLFY_DB, f"SELECT count(*) FROM {table}")}')

    heading('postgres_coordination_counts')
    psql = run(['psql', '-d', 'wolfy', '-Atc', """
        SELECT 'agent_runs:' || status || '=' || count(*) FROM agent_runs GROUP BY status
        UNION ALL SELECT 'agent_tasks:' || status || '=' || count(*) FROM agent_tasks GROUP BY status
        UNION ALL SELECT 'knowledge_chunks_total=' || count(*) FROM knowledge_chunks
        UNION ALL SELECT 'knowledge_chunks_embedded=' || count(embedding) FROM knowledge_chunks
        UNION ALL SELECT 'recommendation_reviews=' || count(*) FROM recommendation_reviews
        ORDER BY 1;
    """], timeout=60)
    print(psql)

    heading('recent_agent_runs_since_prior_ledger')
    psql_recent = run(['psql', '-d', 'wolfy', '-Atc', f"""
        SELECT coalesce(agent_name,'?') || '|' || status || '|' || to_char(started_at AT TIME ZONE 'America/New_York','HH24:MI') || '|' || left(coalesce(summary,error_message,''),120)
        FROM agent_runs
        WHERE started_at >= to_timestamp({int(since)})
        ORDER BY started_at DESC
        LIMIT 30;
    """], timeout=60)
    print(psql_recent)

    heading('recent_usage_or_quota_alerts')
    state = ROOT / 'wolfy' / 'usage_limit_watchdog_state.json'
    if state.exists():
        try:
            data = json.loads(state.read_text())
            print(f'last_checked_at={data.get("last_checked_at")}; seen_events={len(data.get("seen", []))}')
        except Exception as exc:
            print(f'usage_watchdog_state_error={exc}')
    if STATE_DB.exists():
        for r in rows(STATE_DB, '''
            SELECT id, source, message_count, input_tokens, output_tokens, tool_call_count, ended_at
            FROM sessions
            WHERE id LIKE 'cron_%' AND started_at >= ?
            ORDER BY started_at DESC LIMIT 20
        ''', (since,)):
            print(f'{r["id"]}\tmsgs={r["message_count"]}\tin={r["input_tokens"]}\tout={r["output_tokens"]}\ttools={r["tool_call_count"]}\tended={et(r["ended_at"])}')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
