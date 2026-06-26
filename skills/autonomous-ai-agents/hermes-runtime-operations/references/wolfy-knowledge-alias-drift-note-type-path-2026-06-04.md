# Wolfy knowledge alias drift: `note_type` and `path` (2026-06-04)

## Trigger

Mike's cron triage context showed recent Jonah/Wolfy tool errors from ad-hoc SQLite queries against the legacy Wolfy DB:

- `no such column: note_type` from `knowledge_notes`
- `no such column: path` from `knowledge_sources`

Earlier compatibility work had already added `knowledge_notes.title/category/note/content`; newer generated diagnostics kept using additional common names.

## Safe repair pattern

Use non-destructive aliases; do not rewrite canonical schema or drop/recreate data.

Canonical mappings:

| Compatibility alias | Table | Canonical source |
|---|---|---|
| `note_type` | `knowledge_notes` | `category`, falling back to `tags` |
| `path` | `knowledge_sources` | `url_or_reference` |

Implementation steps used:

1. Add nullable columns with `ALTER TABLE ... ADD COLUMN` only if missing.
2. Backfill existing rows:
   - `knowledge_notes.note_type = COALESCE(note_type, category, tags)`
   - `knowledge_sources.path = COALESCE(path, url_or_reference)`
3. Drop/recreate the relevant compatibility triggers inside `mike_safe_autorepair.py` so stale `CREATE TRIGGER IF NOT EXISTS` definitions cannot silently preserve old trigger bodies.
4. Preserve the aliases/triggers in `/root/.hermes/wolfy/init_wolfy_db.py` for fresh DB initialization.
5. Sync the updated autorepair script to:
   - `/root/.hermes/scripts/mike_safe_autorepair.py`
   - `/root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py`
   - `/root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py`

## Verification commands

Run the autorepair twice; first run may report aliases/backfill, second should be silent:

```bash
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py
```

Verify the exact previously failing query shapes:

```bash
python3 - <<'PY'
import sqlite3
con=sqlite3.connect('/root/.hermes/wolfy/wolfy.db')
queries=[
"select id, substr(title,1,80), tags, created_at from knowledge_notes order by id desc limit 1",
"select id, substr(title,1,80), substr(note,1,120), created_at from knowledge_notes order by id desc limit 1",
"select id, substr(title,1,80), category, created_at from knowledge_notes order by id desc limit 1",
"SELECT id, substr(title,1,80), substr(note_type,1,30), created_at FROM knowledge_notes order by id desc limit 1",
"select id,title,status,substr(path,1,80) from knowledge_sources order by id desc limit 1",
]
for q in queries:
    print('OK', q, list(con.execute(q))[:1])
PY
```

Then run the normal Mike operations smokes:

```bash
cd /root/.hermes/wolfy && python3 -m pytest -q test_agent_coordination_smoke.py
python3 /root/.hermes/wolfy/embed_knowledge_chunks.py
python3 /root/.hermes/wolfy/cleanup_stale_agent_coordination.py
python3 /root/.hermes/wolfy/capture_usage_snapshot.py
/root/.hermes/wolfy/check_postgres_requirements.py
```

Expected healthy result: agent coordination tests pass, script-only helpers are silent, Postgres guard is OK, and alias queries return rows instead of schema errors.

## Reporting nuance

Recent log tails are triage leads, not current truth. After adding aliases, search logs for fresh occurrences of the exact schema errors; do not report old historical `no such column` lines as still broken if direct queries and subsequent cron/smoke tests pass.
