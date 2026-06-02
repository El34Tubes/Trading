# Wolfy cron usage -> Postgres agent_runs sync (2026-05-31)

## Context

Mike's ops lane needed per-agent LLM usage/cost accounting for the Wolfy/Jonah/Sentinel research desk. Hermes already records real cron session token counters in `~/.hermes/state.db.sessions`; Wolfy's Postgres `agent_runs` table is the durable coordination ledger.

## Durable pattern

Use a script-only, no-agent sync that joins:

- Hermes cron session rows from `/root/.hermes/state.db`, where cron session IDs look like `cron_<job_id>_<YYYYMMDD>_<HHMMSS>`.
- Cron job metadata from `hermes --profile default cron list --all`.
- Wolfy Postgres `agent_runs`, using one row per cron session.

The sync should be non-destructive and idempotent:

- `ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS session_id TEXT`
- `ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS cron_job_id TEXT`
- `ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS source TEXT`
- add message/tool/cache/reasoning counter columns if missing
- `CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_runs_session_id ON agent_runs(session_id) WHERE session_id IS NOT NULL`
- upsert on `session_id`

Classify agent/role from cron job name where possible:

- Jonah -> `agent_name='Jonah'`, `role='research'`
- Wolfy -> `agent_name='Wolfy'`, `role='analysis'` or alpha-specific role if the job wrapper starts its own run
- Sentinel -> `agent_name='Sentinel'`, `role='review'`
- Yang -> `agent_name='Yang'`, `role='technical_analysis'`
- Clerky -> `agent_name='Clerky'`, `role='admin_reporting'`
- Mike -> `agent_name='Mike'`, `role='operations'`

Treat cron sessions with `total_tokens=0` for non-script analytical agents as `blocked` and include an error note like: likely provider/usage-limit/startup failure; check Hermes cron logs. Do not fabricate token counts.

## Installed files from this run

- `/root/.hermes/wolfy/sync_cron_usage_to_agent_runs.py`
- `/root/.hermes/scripts/wolfy_sync_cron_usage_to_agent_runs.py`
- `/root/.hermes/profiles/mike/scripts/wolfy_sync_cron_usage_to_agent_runs.py`
- `/root/.hermes/profiles/clerky/scripts/wolfy_sync_cron_usage_to_agent_runs.py`

`/root/.hermes/wolfy/capture_usage_snapshot.py` now runs the sync silently before writing the aggregate `agent_usage_snapshots` row. Capture stdout from the helper so the no-agent snapshot job remains silent unless thresholds/errors occur.

## Verification recipe

```bash
cd /root/.hermes/wolfy
python3 -m py_compile sync_cron_usage_to_agent_runs.py capture_usage_snapshot.py
python3 sync_cron_usage_to_agent_runs.py --since-days 2 --summary
python3 capture_usage_snapshot.py | wc -c   # should be 0 in normal/no-alert state
psql -d wolfy -c "SELECT agent_name, status, count(*) AS runs, coalesce(sum(total_tokens),0) AS tokens FROM agent_runs WHERE source='cron' AND started_at >= now() - interval '24 hours' GROUP BY agent_name,status ORDER BY agent_name,status;"
pytest -q test_agent_coordination_smoke.py tests/test_embed_knowledge_chunks.py
```

## Related compatibility fix

A previous alpha-search worker looked for `/root/.hermes/scripts/wolfy-alpha-search-report.sh`; the active cron job uses `wolfy_alpha_search_context.py`. To preserve compatibility, install a tiny shell wrapper at the legacy path that execs the valid Python wrapper. This is a compatibility bridge, not a new alpha workflow.

```bash
#!/usr/bin/env bash
set -euo pipefail
exec python3 /root/.hermes/scripts/wolfy_alpha_search_context.py "$@"
```

## Pitfalls

- Do not use environment/setup-specific failures as durable negative claims. A 429 usage-limit run should be recorded as a blocked/zero-token run, not as a broken Wolfy/Sentinel/Yang job.
- Do not let script-only watchdogs print normal sync summaries; stdout delivery should remain silent unless there is an actionable alert.
- Do not edit market/trading logic from Mike's ops lane. This sync only accounts for cron/session usage and infrastructure health.
