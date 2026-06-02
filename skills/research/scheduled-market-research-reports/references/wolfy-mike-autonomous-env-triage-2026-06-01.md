# Wolfy Mike autonomous environment triage pattern (2026-06-01)

Context: Mike runs as the IT/admin operations agent for the Wolfy research desk. Mike owns Postgres/storage/cron/script health, not market analysis.

Useful durable pattern from the 2026-06-01 triage run:

1. Treat the injected pre-run triage context as the baseline, but still verify current state before reporting.
2. Check cron jobs on the profile that actually owns Wolfy jobs, not only the active profile. In this setup, Mike may run under `--profile mike` while Wolfy cron jobs are listed under the default profile:
   - `hermes --profile default cron list --all`
   - `hermes --profile mike cron list --all`
   - check Clerky/Yang profiles when a profile-scoped job or wrapper is involved.
3. For safe operations verification, run the deterministic no-agent helpers first:
   - `/root/.hermes/wolfy/check_postgres_requirements.py`
   - `python3 -m pytest -q test_agent_coordination_smoke.py tests/test_embed_knowledge_chunks.py test_recommendation_logger.py test_suspicious_activity.py test_alpha_search_pipeline.py test_insider_buying.py` from `/root/.hermes/wolfy`
   - `python3 /root/.hermes/wolfy/mike_safe_autorepair.py`
4. `mike_safe_autorepair.py` is intentionally silent when healthy. Empty stdout with exit code 0 is success, not a missing report.
5. Profile wrapper drift is a safe, reversible repair. Keep global wrappers in `/root/.hermes/scripts/` synchronized into profile script directories when cron jobs may run under profile scope. The known bootstrap issue is that profile-scoped cron jobs need their wrapper under that profile's `scripts/` directory unless the job uses a valid absolute path.
6. When reviewing Postgres run ledgers, a single `agent_runs.status='started'` row may simply be the currently running Mike cron session. Do not mark it stale while the session is active; look at `started_at`, `session_id`, and current cron context.
7. If all checks pass and there are no new actionable failures, use the scheduled-job delivery convention: final response exactly `[SILENT]` to suppress noise.

Do not capture transient missing-file/read errors after the wrapper exists and tests pass. The durable learning is the verification/synchronization pattern, not the temporary failure.