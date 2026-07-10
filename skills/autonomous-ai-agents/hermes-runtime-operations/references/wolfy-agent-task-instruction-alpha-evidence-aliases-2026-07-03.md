# Wolfy agent_tasks.instruction and alpha_leads.evidence compatibility aliases (2026-07-03)

## Trigger

Mike ops saw Jonah/Alpha ad-hoc probes fail against Postgres with missing compatibility columns:

- `agent_tasks.instruction` expected by a scratch task query, while canonical task prose lived in `agent_tasks.instructions` / `description`.
- `alpha_leads.evidence` expected by a scratch Alpha/Jonah query, while evidence lived in `raw_payload`, `rationale`, `summary`, `thesis`, or the `alpha_search_leads` view.

These were durable schema-drift issues, not market-analysis issues.

## Safe repair pattern

Use non-destructive aliases and preserve them in both the initializer and autorepair layer:

1. Add nullable alias columns:
   - `ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS instruction TEXT;`
   - `ALTER TABLE alpha_leads ADD COLUMN IF NOT EXISTS evidence TEXT;`
2. Backfill without overwriting canonical content:
   - `agent_tasks.instruction = COALESCE(instruction, instructions, description)`
   - `alpha_leads.evidence = COALESCE(evidence, raw_payload->>'evidence', raw_payload->>'rationale', raw_payload->>'summary', thesis, title)`
3. Update `wolfy_sync_agent_tasks_aliases()` so new/updated task rows populate `instruction` and include it in `payload`.
4. Update `wolfy_sync_alpha_leads_aliases()` so new/updated alpha-lead rows populate `evidence`.
5. Update the `alpha_search_leads` compatibility view to project `COALESCE(evidence, rationale, summary, thesis, raw_payload->>'evidence', raw_payload->>'rationale', title) AS evidence`.
6. Preserve the same changes in:
   - `/root/.hermes/wolfy/postgres_init.sql`
   - canonical `/root/.hermes/scripts/mike_safe_autorepair.py`
   - synced Wolfy/Mike/Clerky autorepair copies via the autorepair script.

## Verification

Run real probes after patching:

```bash
python3 -m py_compile \
  /root/.hermes/scripts/mike_safe_autorepair.py \
  /root/.hermes/wolfy/mike_safe_autorepair.py \
  /root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py \
  /root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py

/root/.hermes/scripts/mike_safe_autorepair.py
/root/.hermes/scripts/mike_safe_autorepair.py   # second run should be silent

psql -d wolfy -v ON_ERROR_STOP=1 -c "
select column_name from information_schema.columns
 where table_name='agent_tasks' and column_name in ('instruction','instructions') order by 1;
select column_name from information_schema.columns
 where table_name='alpha_leads' and column_name='evidence';
select count(*) filter (where instruction is not null) as tasks_with_instruction, count(*) as tasks_total from agent_tasks;
select count(*) filter (where evidence is not null) as leads_with_evidence, count(*) as leads_total from alpha_leads;
"

python3 /root/.hermes/wolfy/tmp_hood_3308_query.py >/tmp/tmp_hood_3308_query.out
psql -d wolfy -v ON_ERROR_STOP=1 -c "
select id,left(instruction,80) from agent_tasks where id=3308;
select id,ticker,left(evidence,120) from alpha_leads where ticker='HOOD' order by id desc limit 3;
select id,ticker,left(evidence,120) from alpha_search_leads where ticker='HOOD' order by id desc limit 3;
"
```

Expected healthy shape from the original repair: aliases exist, all existing rows are populated, exact HOOD scratch probe exits 0, autorepair second run is silent, and coordination smokes remain at zero stale/duplicate/synthetic noise.

## Pitfalls

- Do not treat these as canonical schema migrations. Canonical task prose remains `description`/`instructions`; canonical alpha evidence may still be JSON/raw-payload driven.
- Patch the preservation layers even if the live DB already has the aliases, otherwise future init/autorepair cycles can regress.
- Avoid rewriting market logic or recommendations; this is compatibility plumbing only.
