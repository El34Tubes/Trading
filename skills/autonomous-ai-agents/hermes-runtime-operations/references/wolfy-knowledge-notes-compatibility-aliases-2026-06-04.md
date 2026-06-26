# Wolfy `knowledge_notes` SQLite compatibility aliases (2026-06-04)

## Trigger

Mike triage saw repeated Jonah/Wolfy cron/tool errors from ad-hoc or LLM-generated SQLite queries that assumed `knowledge_notes` had common note-ledger columns such as `title`, `category`, `note`, or `content`:

- `no such column: title`
- tuple unpacking errors after retrying different projections

Canonical Wolfy SQLite schema uses:

- `topic`
- `principle`
- `summary`
- `application_to_wolfy`
- `tags`

## Safe repair pattern

Use non-destructive compatibility aliases rather than rewriting consumers or changing canonical writes:

```sql
ALTER TABLE knowledge_notes ADD COLUMN title TEXT;
ALTER TABLE knowledge_notes ADD COLUMN category TEXT;
ALTER TABLE knowledge_notes ADD COLUMN note TEXT;
ALTER TABLE knowledge_notes ADD COLUMN content TEXT;

UPDATE knowledge_notes
SET title=COALESCE(title, topic),
    category=COALESCE(category, tags),
    note=COALESCE(note, summary),
    content=COALESCE(content, summary)
WHERE title IS NULL OR category IS NULL OR note IS NULL OR content IS NULL;
```

Then add mirror triggers so future rows stay compatible:

```sql
CREATE TRIGGER IF NOT EXISTS trg_knowledge_notes_alias_after_insert
AFTER INSERT ON knowledge_notes
FOR EACH ROW
WHEN NEW.title IS NULL OR NEW.category IS NULL OR NEW.note IS NULL OR NEW.content IS NULL
BEGIN
  UPDATE knowledge_notes
  SET title=COALESCE(NEW.title, NEW.topic),
      category=COALESCE(NEW.category, NEW.tags),
      note=COALESCE(NEW.note, NEW.summary),
      content=COALESCE(NEW.content, NEW.summary)
  WHERE id=NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_knowledge_notes_alias_after_update
AFTER UPDATE OF topic, tags, summary, title, category, note, content ON knowledge_notes
FOR EACH ROW
WHEN NEW.title IS NULL OR NEW.category IS NULL OR NEW.note IS NULL OR NEW.content IS NULL
BEGIN
  UPDATE knowledge_notes
  SET title=COALESCE(NEW.title, NEW.topic),
      category=COALESCE(NEW.category, NEW.tags),
      note=COALESCE(NEW.note, NEW.summary),
      content=COALESCE(NEW.content, NEW.summary)
  WHERE id=NEW.id;
END;
```

## Durability requirements

1. Add the aliases/triggers to `/root/.hermes/wolfy/init_wolfy_db.py` so fresh SQLite DBs include them.
2. Teach `/root/.hermes/wolfy/mike_safe_autorepair.py` to reapply/backfill aliases and triggers.
3. Sync autorepair to global and profile wrappers:
   - `/root/.hermes/scripts/mike_safe_autorepair.py`
   - `/root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py`
   - `/root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py`
4. Verify the second autorepair run is silent.

## Verification commands

```bash
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py  # should be silent
sqlite3 /root/.hermes/wolfy/wolfy.db "
  select id, substr(title,1,80), tags, created_at
  from knowledge_notes order by id desc limit 3;
  select id, substr(title,1,80), category, created_at
  from knowledge_notes order by id desc limit 3;
  select name from sqlite_master
  where type='trigger' and name like 'trg_knowledge_notes_alias%';
"
sha256sum \
  /root/.hermes/wolfy/mike_safe_autorepair.py \
  /root/.hermes/scripts/mike_safe_autorepair.py \
  /root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py \
  /root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py
```

## Reporting nuance

Treat the original query failures as schema-compatibility drift, not broken Jonah research. Report provider HTTP 429s separately as usage-limit blockers, not infrastructure failures.
