# Profile Cron Operations Triage

Use this when a Hermes operations/admin profile is auditing production cron jobs that may actually live under another profile.

## Pattern

1. Check both the active/admin profile and the owning production profile:
   - `hermes cron list --all`
   - `hermes --profile default cron list --all`
   - Add worker profiles explicitly when jobs list `Profile: clerky`, `Profile: yang`, etc.
2. For profile-scoped jobs with relative `Script:` paths, verify wrapper scripts exist under that profile's `scripts/` directory and are synchronized with the global wrappers. Hash comparison is a quick safe check:
   - `sha256sum /root/.hermes/scripts/<script>.py /root/.hermes/profiles/<profile>/scripts/<script>.py`
3. Treat no-agent/script-only watchdogs with empty stdout and exit code 0 as healthy silent runs. Report only nonzero exits or actionable output.
4. If `hermes doctor` reports `Skills Hub directory not initialized`, initialize it non-destructively with `hermes skills list`, then rerun doctor.
5. For Wolfy-style Postgres usage ledgers, sync Hermes cron sessions into `agent_runs` before interpreting usage totals. A healthy sync may report `inserted=0 updated=N` when it is only refreshing existing rows.
6. When inspecting stale coordination rows, do not classify the currently running cron session's `agent_runs.status='started'` row as stale. Compare `started_at`/age and the current job/session before blocking it.
7. For storage checks, report actual `df` and project-directory size; do not infer disk pressure from database activity alone.

## Reporting shape

Keep final reports grouped as: fixed, verified, remaining/blockers, next autonomous action. Credential/API-key gaps are setup-needed blockers, not infrastructure failures.
