#!/usr/bin/env python3
"""Collect compact Wolfy/Mike environment diagnostics for autonomous repair runs."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path('/root/.hermes/wolfy')
EASTERN = ZoneInfo('America/New_York')
EOD_INGEST_WINDOW_START = time(16, 25)
EOD_INGEST_WINDOW_END = time(17, 10)


def in_eod_ingest_window(now: datetime | None = None) -> bool:
    """Return true while Mike's LLM triage should yield to EOD no-agent shards."""
    if os.getenv('MIKE_TRIAGE_FORCE') == '1':
        return False
    current = now or datetime.now(EASTERN)
    return current.weekday() < 5 and EOD_INGEST_WINDOW_START <= current.time() <= EOD_INGEST_WINDOW_END


def budget_block_reason() -> str | None:
    """Return the budget-gate block line when Mike's LLM triage should skip."""
    if os.getenv('MIKE_TRIAGE_FORCE') == '1':
        return None
    gate = ROOT / 'guardian' / 'budget_gate.py'
    if not gate.exists():
        return None
    try:
        proc = subprocess.run(['python3', str(gate), '--no-record'], text=True, capture_output=True, timeout=30)
    except Exception as exc:
        # Do not hide operational triage if the guard itself is broken; the LLM run can report it.
        print(f"budget_gate_check_error: {type(exc).__name__}: {exc}")
        return None
    out = ((proc.stdout or '') + (proc.stderr or '')).strip()
    first_line = next((line.strip() for line in out.splitlines() if line.strip()), '')
    if first_line.startswith('BUDGET=block'):
        return first_line
    return None


def run(
    label: str,
    cmd: list[str],
    cwd: str | None = None,
    max_chars: int = 6000,
    timeout: int = 90,
) -> None:
    print(f"\n## {label}")
    try:
        proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout)
        out = (proc.stdout or '') + (proc.stderr or '')
        print(f"exit_code={proc.returncode}")
        if len(out) > max_chars:
            out = out[-max_chars:]
            print(f"[truncated to last {max_chars} chars]")
        print(out.strip() or '(no output)')
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")


def main() -> int:
    print("MIKE_AUTONOMOUS_ENV_TRIAGE_CONTEXT")
    if in_eod_ingest_window():
        print("skipped: yielding Mike LLM triage during Wolfy EOD ingest/signals window")
        print(json.dumps({"wakeAgent": False, "reason": "eod_ingest_window"}))
        return 0
    block = budget_block_reason()
    if block:
        print(f"skipped: budget {block}")
        print(json.dumps({"wakeAgent": False, "reason": "budget"}))
        return 0
    print("Role: Mike handles IT/admin operations only: Postgres, storage, usage limits, cron health, broken scripts/tests. No market analysis.")
    print("Autonomy boundary: fix safe non-destructive issues directly; do not drop databases, delete user data, upgrade Postgres major versions, or change trading logic.")
    run('date', ['date', '-Is'])
    run('profiles', ['hermes', 'profile', 'list'])
    run('mike cron list', ['hermes', 'cron', 'list'])
    run('default cron list', ['hermes', '--profile', 'default', 'cron', 'list', '--all'], max_chars=12000)
    run('kanban wolfy', ['hermes', 'kanban', '--board', 'wolfy', 'list'])
    run('hermes doctor', ['hermes', 'doctor'], timeout=180)
    run('postgres requirements guard', [str(ROOT / 'check_postgres_requirements.py')])
    run('postgres schema/counts', ['psql', '-d', 'wolfy', '-c', "SELECT 'agent_tasks' AS table, status, count(*) FROM agent_tasks GROUP BY status UNION ALL SELECT 'agent_runs', status, count(*) FROM agent_runs GROUP BY status ORDER BY 1,2; SELECT count(*) AS knowledge_chunks, count(embedding) AS embedded_chunks FROM knowledge_chunks;"])
    run('agent coordination read-only smoke', ['psql', '-d', 'wolfy', '-v', 'ON_ERROR_STOP=1', '-c', "SELECT count(*) AS stale_started_runs FROM agent_runs WHERE status='started' AND started_at < now() - interval '2 hours'; SELECT count(*) AS synthetic_blocked_tasks FROM agent_tasks WHERE status='blocked' AND title='Smoke blocked task' AND source_fingerprint LIKE 'smoke-block-%'; SELECT count(*) AS duplicate_claim_noise FROM agent_runs WHERE status='blocked' AND error_message='duplicate-or-already-claimed' AND started_at > now() - interval '24 hours';"])
    run('embedding sync smoke', ['python3', str(ROOT / 'embed_knowledge_chunks.py')])
    run('stale coordination cleanup smoke', ['python3', str(ROOT / 'cleanup_stale_agent_coordination.py')])
    run('usage snapshot smoke', ['python3', str(ROOT / 'capture_usage_snapshot.py')])
    run('recent errors tail', ['bash', '-lc', 'tail -120 /root/.hermes/logs/errors.log 2>/dev/null || true'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
