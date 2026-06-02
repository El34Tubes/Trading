#!/usr/bin/env python3
"""Script-only safe autorepair for Mike's Wolfy/Hermes operations lane.

This does deterministic, non-destructive fixes that do not need an LLM.
It stays silent when everything is healthy.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path('/root/.hermes')
SCRIPTS = ROOT / 'scripts'
WOLFY = ROOT / 'wolfy'
MIKE = ROOT / 'profiles' / 'mike' / 'scripts'
CLERKY = ROOT / 'profiles' / 'clerky' / 'scripts'

MIKE_SCRIPTS = [
    'wolfy_storage_watchdog.py',
    'wolfy_usage_limit_watchdog.py',
    'wolfy_embed_knowledge_chunks.py',
    'wolfy_cleanup_stale_agent_coordination.py',
    'wolfy_capture_usage_snapshot.py',
    'wolfy_sync_cron_usage_to_agent_runs.py',
    'mike_environment_triage_context.py',
]
CLERKY_SCRIPTS = [
    'wolfy_clerky_activity_context.py',
    'wolfy_kanban_allocator.py',
    'wolfy_sync_cron_usage_to_agent_runs.py',
]
LEGACY_WRAPPERS = {
    'wolfy-alpha-search-report.sh': "#!/usr/bin/env bash\nset -euo pipefail\nexec python3 /root/.hermes/wolfy/alpha_search_context.py \"$@\"\n",
    'wolfy_embed_knowledge_chunks.py': """#!/usr/bin/env python3
\"\"\"Compatibility wrapper for Wolfy's knowledge embedding sync.

Cron/profile wrappers and older diagnostics may still call this legacy name;
the live implementation is /root/.hermes/wolfy/embed_knowledge_chunks.py.
\"\"\"
from __future__ import annotations

import subprocess
import sys

SCRIPT = '/root/.hermes/wolfy/embed_knowledge_chunks.py'

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, SCRIPT, '--limit', '200', *sys.argv[1:]]))
""",
}
LEGACY_WOLFY_WRAPPERS = {
    'wolfy_embed_knowledge_chunks.py': """#!/usr/bin/env python3
\"\"\"Compatibility wrapper for the Wolfy knowledge embedding sync.

Some diagnostics and older cron/context snippets refer to this legacy filename;
the live implementation is embed_knowledge_chunks.py.
\"\"\"
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name('embed_knowledge_chunks.py')

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable, str(SCRIPT), '--limit', '200', *sys.argv[1:]]))
""",
}


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 90) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True, timeout=timeout)
    return proc.returncode, ((proc.stdout or '') + (proc.stderr or '')).strip()


def sync_scripts() -> list[str]:
    changed: list[str] = []
    for name, content in LEGACY_WRAPPERS.items():
        dest = SCRIPTS / name
        if not dest.exists() or dest.read_text() != content:
            dest.write_text(content)
            dest.chmod(0o755)
            changed.append(f'WROTE_LEGACY_WRAPPER {dest}')
    for name, content in LEGACY_WOLFY_WRAPPERS.items():
        dest = WOLFY / name
        if not dest.exists() or dest.read_text() != content:
            dest.write_text(content)
            dest.chmod(0o755)
            changed.append(f'WROTE_LEGACY_WOLFY_WRAPPER {dest}')
    for dest_dir, names in [(MIKE, MIKE_SCRIPTS), (CLERKY, CLERKY_SCRIPTS)]:
        dest_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            src = SCRIPTS / name
            dest = dest_dir / name
            if not src.exists():
                changed.append(f'MISSING_SOURCE_SCRIPT {src}')
                continue
            if not dest.exists() or src.read_bytes() != dest.read_bytes():
                shutil.copy2(src, dest)
                dest.chmod(0o755)
                changed.append(f'SYNCED_PROFILE_SCRIPT {dest}')
    return changed


def main() -> int:
    reports: list[str] = []
    reports.extend(sync_scripts())

    checks = [
        ('postgres_guard', [str(WOLFY / 'check_postgres_requirements.py')], None),
        ('agent_coordination_smoke', ['python3', '-m', 'pytest', '-q', 'test_agent_coordination_smoke.py'], WOLFY),
        ('stale_coordination_cleanup', ['python3', str(WOLFY / 'cleanup_stale_agent_coordination.py')], None),
        ('embedding_sync', ['python3', str(WOLFY / 'embed_knowledge_chunks.py')], None),
        ('usage_snapshot', ['python3', str(WOLFY / 'capture_usage_snapshot.py')], None),
    ]
    for label, cmd, cwd in checks:
        code, out = run(cmd, cwd=cwd)
        if code != 0:
            reports.append(f'FAILED {label}: {out[-1000:]}')
        elif out and any(word in out.lower() for word in ('error', 'failed', 'blocked', 'missing')):
            reports.append(f'CHECK_OUTPUT {label}: {out[-1000:]}')

    if reports:
        print('Mike safe autorepair report:')
        for item in reports:
            print(f'- {item}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
