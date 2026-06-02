#!/usr/bin/env python3
"""Collect compact Wolfy/Mike environment diagnostics for autonomous repair runs."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path('/root/.hermes/wolfy')


def run(label: str, cmd: list[str], cwd: str | None = None, max_chars: int = 6000) -> None:
    print(f"\n## {label}")
    try:
        proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=90)
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
    print("Role: Mike handles IT/admin operations only: Postgres, storage, usage limits, cron health, broken scripts/tests. No market analysis.")
    print("Autonomy boundary: fix safe non-destructive issues directly; do not drop databases, delete user data, upgrade Postgres major versions, or change trading logic.")
    run('date', ['date', '-Is'])
    run('profiles', ['hermes', 'profile', 'list'])
    run('mike cron list', ['hermes', 'cron', 'list'])
    run('default cron list', ['hermes', '--profile', 'default', 'cron', 'list', '--all'], max_chars=12000)
    run('kanban wolfy', ['hermes', 'kanban', '--board', 'wolfy', 'list'])
    run('hermes doctor', ['hermes', 'doctor'])
    run('postgres requirements guard', [str(ROOT / 'check_postgres_requirements.py')])
    run('postgres schema/counts', ['psql', '-d', 'wolfy', '-c', "SELECT 'agent_tasks' AS table, status, count(*) FROM agent_tasks GROUP BY status UNION ALL SELECT 'agent_runs', status, count(*) FROM agent_runs GROUP BY status ORDER BY 1,2; SELECT count(*) AS knowledge_chunks, count(embedding) AS embedded_chunks FROM knowledge_chunks;"])
    run('agent coordination smoke tests', ['python3', '-m', 'pytest', '-q', 'test_agent_coordination_smoke.py'], cwd=str(ROOT))
    run('embedding sync smoke', ['python3', str(ROOT / 'embed_knowledge_chunks.py')])
    run('stale coordination cleanup smoke', ['python3', str(ROOT / 'cleanup_stale_agent_coordination.py')])
    run('usage snapshot smoke', ['python3', str(ROOT / 'capture_usage_snapshot.py')])
    run('recent errors tail', ['bash', '-lc', 'tail -120 /root/.hermes/logs/errors.log 2>/dev/null || true'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
