# Wolfy source-file inbox pattern — 2026-06-01

Context: the user was SSH'd into the Wolfy host and asked where to drop semi-structured source material before it is persisted into the knowledge base database.

Durable pattern:

- Canonical inbox: `/root/.hermes/wolfy/sources/inbox/`
- Human-facing README: `/root/.hermes/wolfy/sources/inbox/README.md`
- Queue script: `/root/.hermes/wolfy/queue_knowledge_source_files.py`
- Authoritative source queue remains SQLite: `/root/.hermes/wolfy/wolfy.db`, table `knowledge_sources`

Supported inbox file types:

- `.md`
- `.txt`
- `.csv`
- `.json`
- `.yaml` / `.yml`

Queue command after adding files:

```bash
cd /root/.hermes/wolfy
python3 queue_knowledge_source_files.py
```

Queue behavior:

- Recursively scans `sources/inbox/`.
- Skips `README.md` and `*.source.json` sidecars.
- Inserts one `knowledge_sources` row per new file.
- Stores the file's absolute path in `url_or_reference`.
- Dedupes by `url_or_reference`.
- Defaults to `source_type='user_file'`, `access_mode='user_provided_file'`, `copyright_status='user_provided_or_public'`, `priority=20`, `quality_score=0.75`, `status='queued'`.

Optional sidecar metadata:

For `foo.md`, add sibling `foo.source.json`:

```json
{
  "title": "Minervini VCP notes from user",
  "author": "Mark Minervini / user notes",
  "source_type": "user_notes",
  "access_mode": "user_provided_file",
  "copyright_status": "user_provided_notes",
  "priority": 10,
  "quality_score": 0.85
}
```

Jonah context update:

`/root/.hermes/wolfy/hourly_knowledge_context.py` now checks whether `knowledge_sources.url_or_reference` is an existing absolute local path. If so, it prints an explicit instruction to read the local file directly before distilling `knowledge_notes` / `strategy_rules`. If not, it keeps the previous public/legal-source warning.

Verification used in the session:

```bash
python3 -m py_compile /root/.hermes/wolfy/queue_knowledge_source_files.py /root/.hermes/wolfy/hourly_knowledge_context.py
python3 /root/.hermes/wolfy/queue_knowledge_source_files.py --dry-run
```

Operational pitfall:

If the user asks for a filesystem drop zone, do not answer only with `knowledge_sources` SQL. Create or point to the inbox directory and provide the queue command. The database row is the queue marker; the source content should remain readable from the file path until Jonah consumes/distills it.
