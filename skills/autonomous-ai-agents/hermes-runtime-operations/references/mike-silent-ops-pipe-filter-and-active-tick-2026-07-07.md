# Mike silent ops: pipe-filter and active-tick triage (2026-07-07)

Context: scheduled Mike environment triage ran while the default-profile cron scheduler had just-due no-agent jobs and an active Mike LLM cron session (`cron_fdfd5b53b5d5_20260707_120923`). Pre-run context already showed healthy Postgres, watchdogs, embeddings, and default cron jobs.

Reusable lessons:

1. Treat historical `recent errors tail` as leads, not current truth.
   - Rerun the exact scratch probes before adding schema aliases.
   - In this run, `tmp_mu_3411_query.py`, `tmp_crwd_task3409_query.py`, and `tmp_task3408_lead.py` all exited 0, so the prior Jonah scratch warnings were not durable infra drift.

2. Do not pipe Hermes/cron/log output into Python for ad-hoc filtering.
   - A command shaped like `hermes ... cron list --all | python3 -c ...` was blocked by Tirith as `pipe-to-interpreter`.
   - Safe replacement: write CLI output to `/tmp/*.txt`, then inspect with `grep`, `search_files`, or plain file reads. Example:
     ```bash
     hermes --profile default cron list --all >/tmp/default_cron_after.txt
     grep -A12 -B2 -E 'Wolfy config guardian|usage-limit watchdog|safe environment autorepair' /tmp/default_cron_after.txt
     ```

3. Stale `hermes cron status` next-run timestamps can be an active-tick artifact.
   - If `cron status` shows `Next run` in the past by ~1 minute while `/root/.hermes/cron/.tick.lock` was just touched and `agent.log` shows the current Mike ops LLM session still running, do not report the scheduler stuck.
   - Verify direct script smokes instead (`mike_safe_autorepair.py` twice silent, usage watchdog twice silent, guardian wrapper exits 0) and return `[SILENT]` when no actionable issue remains.

4. Minimum healthy silent-run evidence used here:
   - `check_postgres_requirements.py` OK: Postgres 16.14, pg_trgm 1.6, vector 0.6.0.
   - `stale_started_runs=0`, `duplicate_claim_noise=0`.
   - `mike_safe_autorepair.py` first and second runs: exit 0, empty stdout/stderr.
   - `wolfy_usage_limit_watchdog.py` first and second runs: exit 0, empty stdout/stderr.
   - `HERMES_HOME=/root/.hermes/profiles/mike bash /root/.hermes/scripts/wolfy_config_guardian.sh`: exit 0 and `GUARDIAN=ok ... hermes_cron_list_ok;probation_active`.
   - Mike-assigned Wolfy Kanban list had only completed cards.

Reporting rule: if those invariants hold and no file/schema/config fix was made, final response for the scheduled ops job should be exactly `[SILENT]`.
