#!/usr/bin/env python3
"""Guard Postgres maintenance against project technical requirements.

Use before Postgres package updates. It verifies the installed/current major
version is within the project's allowed range and warns if apt candidates would
move beyond that range.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REQ_PATH = Path('/root/.hermes/wolfy/postgres_requirements.json')
PACKAGES = [
    'postgresql',
    'postgresql-16',
    'postgresql-contrib',
    'postgresql-16-pgvector',
    'postgresql-client-16',
    'postgresql-client-common',
    'postgresql-common',
]


def run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT, timeout=60)


def parse_major(version_text: str) -> int | None:
    m = re.search(r'(?:PostgreSQL\)\s*)?(\d+)(?:\.|\+|-)', version_text)
    return int(m.group(1)) if m else None


def apt_candidate(pkg: str) -> str:
    out = run(['apt-cache', 'policy', pkg])
    for line in out.splitlines():
        if line.strip().startswith('Candidate:'):
            return line.split(':', 1)[1].strip()
    return ''


def main() -> int:
    req = json.loads(REQ_PATH.read_text())
    min_major = int(req['postgres']['allowed_major_min'])
    max_major = int(req['postgres']['allowed_major_max'])

    psql_version = run(['psql', '--version']).strip()
    installed_major = parse_major(psql_version)
    if installed_major is None or not (min_major <= installed_major <= max_major):
        print(f'BLOCK: installed Postgres version outside requirements: {psql_version}')
        return 2

    problems: list[str] = []
    candidates: dict[str, str] = {}
    for pkg in PACKAGES:
        cand = apt_candidate(pkg)
        candidates[pkg] = cand
        if pkg.startswith('postgresql') and '-16' not in pkg and pkg not in {'postgresql-contrib', 'postgresql-client-common', 'postgresql-common'}:
            major = parse_major(cand)
            if major is not None and not (min_major <= major <= max_major):
                problems.append(f'{pkg} candidate {cand} outside allowed major {min_major}-{max_major}')
        if pkg in {'postgresql-16', 'postgresql-client-16'} and cand and not cand.startswith('16.'):
            problems.append(f'{pkg} candidate {cand} does not look like PostgreSQL 16')

    # Verify DB extensions exist.
    ext_out = run(['psql', '-d', 'wolfy', '-Atc', "SELECT extname || '=' || extversion FROM pg_extension WHERE extname IN ('vector','pg_trgm') ORDER BY extname;"])
    exts = dict(line.split('=', 1) for line in ext_out.splitlines() if '=' in line)
    for ext_name, ext_req in req['extensions'].items():
        if ext_req.get('required') and ext_name not in exts:
            problems.append(f'missing required extension: {ext_name}')

    if problems:
        print('BLOCK: Postgres update does not meet Wolfy technical requirements.')
        for p in problems:
            print(f'- {p}')
        print('Candidates:')
        for pkg, cand in candidates.items():
            print(f'- {pkg}: {cand}')
        return 2

    print('OK: Postgres maintenance/update is within Wolfy technical requirements.')
    print(f'- installed: {psql_version}')
    print(f'- allowed major: {min_major}-{max_major}')
    for name, ver in sorted(exts.items()):
        print(f'- extension {name}: {ver}')
    print('Allowed command pattern: apt-get install --only-upgrade ' + ' '.join(PACKAGES))
    return 0


if __name__ == '__main__':
    sys.exit(main())
