# Wolfy Alpha Search context wrapper sync

Session pattern from 2026-06-02 Mike operations pass.

## Symptom

Diagnostics or cron tails reference an older Alpha Search context path such as `wolfy_alpha_search_context.py` while the live implementation is `/root/.hermes/wolfy/alpha_search_context.py`. A global wrapper may exist while profile-scoped wrappers are missing or stale.

## Safe repair

Create/refresh compatibility wrappers instead of renaming the live implementation or editing cron jobs destructively:

- `/root/.hermes/wolfy/wolfy_alpha_search_context.py` -> delegates to `alpha_search_context.py` in the same directory.
- `/root/.hermes/scripts/wolfy_alpha_search_context.py` -> delegates to `/root/.hermes/wolfy/alpha_search_context.py`.
- `/root/.hermes/profiles/mike/scripts/wolfy_alpha_search_context.py` -> synced copy of the global wrapper.
- `/root/.hermes/profiles/clerky/scripts/wolfy_alpha_search_context.py` -> synced copy of the global wrapper when Clerky diagnostics may invoke it.

Teach `/root/.hermes/scripts/mike_safe_autorepair.py` to preserve the wrappers and to sync itself into `/root/.hermes/wolfy/mike_safe_autorepair.py` plus Mike/Clerky profile script directories, so the repair survives future no-agent autorepair runs.

## Verification

Run each wrapper path directly and capture the printed `AGENT_RUN_ID`. Because the context script starts a Postgres `agent_runs` row, immediately finish each smoke row with `records_created=0` and a summary such as `Mike smoke-tested alpha context compatibility wrapper; no alpha report generated.`

Then verify:

```bash
python3 /root/.hermes/scripts/mike_safe_autorepair.py   # first run may print sync actions
python3 /root/.hermes/scripts/mike_safe_autorepair.py   # second run should be silent
python3 /root/.hermes/wolfy/check_postgres_requirements.py
cd /root/.hermes/wolfy && python3 -m pytest -q test_agent_coordination_smoke.py
python3 /root/.hermes/wolfy/embed_knowledge_chunks.py
python3 /root/.hermes/wolfy/cleanup_stale_agent_coordination.py
python3 /root/.hermes/wolfy/capture_usage_snapshot.py
hermes --profile default cron list --all
```

If smoke tests intentionally start context/run rows, close them explicitly before final reporting so operations runs do not create stale `started` noise in `agent_runs`.
