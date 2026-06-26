# Wolfy SQLite compatibility alias expansion — 2026-06-04

## Trigger

Mike's autonomous environment triage saw repeated Jonah/Wolfy ad-hoc SQLite query drift in recent cron logs. Earlier repairs covered `knowledge_notes.title/category/note/content/note_type` and `knowledge_sources.path`, but newer generated queries also referenced:

- `knowledge_notes.source_type`
- `knowledge_sources.url`
- `strategy_rules.category`
- `strategy_rules.source_id`
- `strategy_rules.is_active`

These are aliases for diagnostic/report prompt compatibility, not canonical schema replacements.

## Safe repair pattern

1. Add nullable/default alias columns only; do not rewrite or rename canonical columns.
2. Backfill from canonical fields:
   - `knowledge_notes.source_type = COALESCE(source_type, note_type, category, tags)`
   - `knowledge_sources.url = COALESCE(url, url_or_reference)`
   - `strategy_rules.category = COALESCE(category, rule_type)`
   - `strategy_rules.source_id = COALESCE(source_id, source_basis)`
   - `strategy_rules.is_active = COALESCE(is_active, enabled)`
   - Also keep existing `strategy_rules.name/status/asset_class` backfills current.
3. Drop/recreate affected compatibility triggers instead of relying on stale `CREATE TRIGGER IF NOT EXISTS` bodies.
4. Preserve the repair in both:
   - `/root/.hermes/wolfy/init_wolfy_db.py`
   - `/root/.hermes/scripts/mike_safe_autorepair.py`
5. Run the script-only autorepair once to apply/sync wrappers, then run it a second time and expect empty stdout.
6. Sync autorepair wrapper copies to Wolfy/Mike/Clerky profile paths so future profile-scoped diagnostics do not rediscover missing-wrapper or stale-autorepair false alarms.

## Verification commands used

```bash
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py  # second run should be silent
python3 -m py_compile /root/.hermes/scripts/mike_safe_autorepair.py /root/.hermes/wolfy/mike_safe_autorepair.py /root/.hermes/wolfy/init_wolfy_db.py
sqlite3 /root/.hermes/wolfy/wolfy.db "select id,title,url,status from knowledge_sources order by id desc limit 1; select id, substr(title,1,20), source_type, created_at from knowledge_notes order by id desc limit 1; select id, substr(name,1,20), substr(category,1,20), is_active from strategy_rules order by id desc limit 1; select source_id, count(*), group_concat(rule_name, ' | ') from strategy_rules group by source_id limit 1;"
/root/.hermes/wolfy/check_postgres_requirements.py
python3 -m pytest -q /root/.hermes/wolfy/test_agent_coordination_smoke.py
python3 /root/.hermes/wolfy/embed_knowledge_chunks.py
python3 /root/.hermes/wolfy/cleanup_stale_agent_coordination.py
python3 /root/.hermes/wolfy/capture_usage_snapshot.py
python3 /root/.hermes/scripts/wolfy_clerky_activity_context.py
hermes --profile default cron list --all
```

Expected result: compatibility queries exit 0; script-only helpers are silent; Postgres guard remains within the PostgreSQL 16 boundary; cron status is still active, with credential/provider usage-limit failures reported as setup/usage conditions rather than script breakage.

## Pitfall

Do not encode each missing alias as a durable claim that Wolfy scripts are broken. Treat log-tail errors as triage leads, rerun exact queries, then add narrow compatibility aliases only if the current DB still lacks them.
