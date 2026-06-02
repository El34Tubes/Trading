# Wolfy knowledge-source inbox

Drop semi-structured source material here before it is persisted into Wolfy's knowledge database.

Canonical drop directory:

`/root/.hermes/wolfy/sources/inbox/`

Supported source file types:

- `.md`
- `.txt`
- `.csv`
- `.json`
- `.yaml` / `.yml`

Recommended layout:

```text
/root/.hermes/wolfy/sources/inbox/
  2026-06-01-minervini-vcp-notes.md
  2026-06-01-sec-form4-screening-rules.md
  ticker-research/
    XYZ-catalyst-notes.md
```

Optional sidecar metadata file:

For any source file, you may add a sibling `.source.json` file with the same basename.

Example:

`minervini-vcp-notes.md`
`minervini-vcp-notes.source.json`

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

If no sidecar exists, the queue script derives the title from the filename and uses safe defaults.

Queue files into Wolfy's SQLite source table:

```bash
cd /root/.hermes/wolfy
python3 queue_knowledge_source_files.py
```

That inserts rows into `knowledge_sources` with `url_or_reference` pointing at the absolute file path. Jonah then sees them in his normal source queue and can persist distilled `knowledge_notes` / `strategy_rules` into the database.

Copyright/legal rule:

- OK: your own notes, excerpts you have rights to provide, public web docs, public filings, public transcripts.
- Avoid: dumping full copyrighted books/articles unless you own/provide lawful text and want it used as user-provided material.
