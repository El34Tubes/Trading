# Wolfy cron stale tick-lock triage — 2026-06-20

## Trigger

A Mike scheduled operations run saw `hermes --profile default cron status` continue to report a just-due `Next run` (`2026-06-20T11:25:49-04:00`) several minutes after that time. The default cron list still showed the two no-agent jobs due at `11:25:49` / `11:25:51` with their previous `Last run` values.

## Useful probes

Run these before declaring the scheduler stuck or restarting anything:

```bash
hermes --profile default cron status
hermes --profile default cron list --all

# Check whether a tick is in progress or wedged.
python3 -c "from pathlib import Path; import time; p=Path('/root/.hermes/cron/.tick.lock'); print('exists', p.exists()); st=p.stat() if p.exists() else None; print({'size': st.st_size, 'mtime': time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(st.st_mtime)), 'age_seconds': round(time.time()-st.st_mtime,1)} if st else '')"

# Check gateway liveness without touching it.
ps -p <gateway_pid> -o pid,ppid,stat,etime,pcpu,pmem,cmd
ps -L -p <gateway_pid> -o pid,tid,stat,pcpu,comm

# Search for actual cron session creation, not just status output.
# Use search/read tools where available rather than pipe-to-interpreter patterns.
```

## Interpretation pattern

- A stale `Next run` by itself is not enough to report a failure; wait/poll once, especially when another LLM cron run may be occupying the cron ticker.
- If gateway logs around the due time show only `gateway.memory_monitor` heartbeat lines and no `cron_<job_id>...` session, inspect `.tick.lock` age. A zero-byte lock whose mtime matches the pre-run triage time is a triage lead.
- If the no-agent smokes still run silently by direct invocation (`wolfy_embed_knowledge_chunks.py`, `wolfy_cleanup_stale_agent_coordination.py`, `wolfy_capture_usage_snapshot.py`) and Postgres coordination checks are clean, do not turn the run into a user-facing alert unless the scheduler miss persists or blocks a material job.
- Keep the final scheduled Mike report silent (`[SILENT]`) when there is no confirmed actionable issue after verification.

## Verified healthy direct checks from the session

- Postgres guard OK: PostgreSQL 16.14, pg_trgm 1.6, vector 0.6.0 within Wolfy requirements.
- `visible_progress_ledger.py` executable mode was already `755`; compile and `--help` passed.
- `mike_safe_autorepair.py` ran twice with no output.
- Embedding sync, stale coordination cleanup, and usage snapshot direct smokes all ran with no output.
- Postgres coordination checks: `stale_started_runs=0`, `duplicate_claim_noise_24h=0`, `knowledge_chunks total=856 embedded=856 missing=0`.
