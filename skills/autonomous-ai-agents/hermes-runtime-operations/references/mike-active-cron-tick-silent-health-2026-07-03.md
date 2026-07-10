# Mike active cron tick + silent health verification (2026-07-03)

Use this as a concrete example for scheduled Mike operations runs where the safe outcome is `[SILENT]` even though a quick `hermes cron status` still shows a just-due job.

## Situation

- Mike environment triage was itself running as the active LLM cron job.
- `hermes --profile default cron status` showed the next run as a just-due script-only job (`Mike Postgres stale coordination watchdog`).
- `/root/.hermes/cron/.tick.lock` was zero bytes and had an mtime from the start of the active Mike run.
- Recent `agent.log` showed the active `cron_fdfd5b53b5d5_...` Mike session still executing on the cron ticker.
- Direct script smokes were healthy and silent.

## Safe interpretation

Do **not** report a stuck scheduler just because `cron status` still lists a just-due script-only job while the current LLM cron session is active. In this shape, the active LLM cron run can hold the ticker and leave due no-agent jobs listed at their old `Next run` until it exits.

## Verification pattern

1. Confirm the production/default cron inventory:
   - `hermes --profile default cron list --all`
   - `hermes --profile default cron status`
2. Confirm current active run vs stale ledger noise:
   - Query `agent_runs` for `status='started'` and exclude/explain the current Mike cron session if only a few minutes old.
   - Check stale-started count with a threshold such as `started_at < now() - interval '20 minutes'`.
3. Run direct silent smokes for script-only helpers instead of waiting for the ticker:
   - `python3 /root/.hermes/scripts/wolfy_embed_knowledge_chunks.py`
   - `python3 /root/.hermes/scripts/wolfy_cleanup_stale_agent_coordination.py`
   - `python3 /root/.hermes/scripts/wolfy_capture_usage_snapshot.py`
   - second `python3 /root/.hermes/scripts/mike_safe_autorepair.py` should be silent
4. Check tick lock and logs only as triage context, not as standalone failure proof:
   - `/root/.hermes/cron/.tick.lock` may be global even for default-profile jobs.
   - `agent.log` should show the active Mike session making progress if the ticker is occupied.
5. If all invariants are healthy and no new durable fix was made, return exactly `[SILENT]`.

## Concrete healthy outputs from this run

- Postgres guard: `OK: Postgres maintenance/update is within Wolfy technical requirements.`
- Coordination health: `stale_started_runs=0`, `duplicate_claim_noise=0`.
- Embeddings: `knowledge_chunks total=994 embedded=994`.
- Guardian: `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;hermes_cron_list_ok;no_probation`.
- Visible ledger regression: `2 passed`.
- No Mike-assigned Wolfy Kanban cards were open.

## Pitfall

Do not pipe live Hermes/cron output into an interpreter for ad-hoc filtering. Use plain CLI output, temp files, `read_file`, or direct SQL instead.