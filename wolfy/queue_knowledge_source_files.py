#!/usr/bin/env python3
"""Queue user-provided source files from sources/inbox into Wolfy's knowledge_sources table.

The file stays on disk; SQLite stores its absolute path in url_or_reference so
Jonah can consume it through the normal knowledge-source workflow.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path('/root/.hermes/wolfy')
DB = ROOT / 'wolfy.db'
INBOX = ROOT / 'sources' / 'inbox'
SUPPORTED_EXTS = {'.md', '.txt', '.csv', '.json', '.yaml', '.yml'}
SKIP_SUFFIXES = {'.source.json'}


def title_from_path(path: Path) -> str:
    text = path.stem.replace('_', ' ').replace('-', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:1].upper() + text[1:] if text else path.name


def sidecar_path(path: Path) -> Path:
    return path.with_suffix('.source.json')


def load_sidecar(path: Path) -> dict[str, Any]:
    sc = sidecar_path(path)
    if not sc.exists():
        return {}
    try:
        data = json.loads(sc.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('sidecar JSON root must be an object')
        return data
    except Exception as e:
        raise RuntimeError(f'Invalid sidecar {sc}: {e}') from e


def iter_source_files(inbox: Path) -> list[Path]:
    if not inbox.exists():
        return []
    files: list[Path] = []
    for p in inbox.rglob('*'):
        if not p.is_file():
            continue
        if p.name == 'README.md':
            continue
        if any(p.name.endswith(suffix) for suffix in SKIP_SUFFIXES):
            continue
        if p.suffix.lower() in SUPPORTED_EXTS:
            files.append(p)
    return sorted(files)


def queue_file(con: sqlite3.Connection, path: Path, dry_run: bool = False) -> tuple[str, int | None, str]:
    abs_path = str(path.resolve())
    existing = con.execute(
        'SELECT id, status FROM knowledge_sources WHERE url_or_reference=?',
        (abs_path,),
    ).fetchone()
    if existing:
        return ('exists', int(existing[0]), str(existing[1]))

    meta = load_sidecar(path)
    title = str(meta.get('title') or title_from_path(path))
    author = meta.get('author')
    source_type = str(meta.get('source_type') or 'user_file')
    access_mode = str(meta.get('access_mode') or 'user_provided_file')
    copyright_status = str(meta.get('copyright_status') or 'user_provided_or_public')
    priority = int(meta.get('priority') or 20)
    quality_score = float(meta.get('quality_score') or 0.75)
    status = str(meta.get('status') or 'queued')

    if dry_run:
        return ('would_insert', None, status)

    cur = con.execute(
        '''
        INSERT INTO knowledge_sources
        (title, author, source_type, url_or_reference, access_mode, copyright_status, priority, quality_score, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (title, author, source_type, abs_path, access_mode, copyright_status, priority, quality_score, status),
    )
    return ('inserted', int(cur.lastrowid), status)


def main() -> None:
    parser = argparse.ArgumentParser(description='Queue files from sources/inbox into knowledge_sources.')
    parser.add_argument('--inbox', type=Path, default=INBOX, help=f'default: {INBOX}')
    parser.add_argument('--db', type=Path, default=DB, help=f'default: {DB}')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    args.inbox.mkdir(parents=True, exist_ok=True)
    if not args.db.exists():
        raise SystemExit(f'DB not found: {args.db}')

    files = iter_source_files(args.inbox)
    if not files:
        print(f'No source files found in {args.inbox}')
        return

    with sqlite3.connect(args.db) as con:
        for path in files:
            action, row_id, status = queue_file(con, path, dry_run=args.dry_run)
            row = f'id={row_id}' if row_id is not None else 'id=pending'
            print(f'{action}: {row} status={status} path={path.resolve()}')
        if args.dry_run:
            con.rollback()
        else:
            con.commit()


if __name__ == '__main__':
    main()
