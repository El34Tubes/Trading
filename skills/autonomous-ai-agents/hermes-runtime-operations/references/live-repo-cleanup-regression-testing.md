# Regression testing after cleanup in a live operations repository

Use this pattern after deleting scratch artifacts, tracked one-shot utilities, snapshots, or generated runtime state from a repository that is also a live Hermes/Wolfy home.

## Verification matrix

1. **Project tests from the project directory**
   - Run the complete project suite from its own directory, not the repository root when profile-synchronized skills contain duplicate test module names.
   - Run a targeted suite covering the changed subsystem and adjacent safety paths.
   - For Wolfy, use a temporary pytest environment with `pytest`, `psycopg[binary]`, and `pyyaml` when the repository has no local test environment.

2. **Static and repository integrity**
   - Compile tracked Python in bounded argument chunks.
   - Exclude vendored/synchronized skill trees when the goal is application-code compilation and those trees have separate dependency contracts.
   - Run `git diff --check` on each cleanup commit independently. A repository-wide check can report unrelated dirty-tree whitespace; do not attribute that to the cleanup without path/commit isolation.
   - Verify local HEAD equals the intended remote branch and run a Git integrity check.

3. **Cron resolution and health**
   - Parse `cron/jobs.json` as either a top-level list or `{ "jobs": [...] }`.
   - Relative cron scripts resolve through Hermes's script directory (normally `/root/.hermes/scripts/`), not necessarily the repository root or the job workdir. Check the actual scheduler resolution path before declaring scripts missing.
   - Confirm every script-backed job resolves, scheduler heartbeat is fresh, jobs remain enabled, and latest runs are healthy.
   - Compile cron-facing wrappers and their delegated implementations.

4. **Use the real runtime interpreter**
   - Invoke operational wrappers with the interpreter/environment used by Hermes cron. System `python3` may lack runtime packages even when cron is healthy.
   - A manual smoke that fails only because it used the wrong interpreter is a harness error, not an application regression. Rerun with the real runtime before reporting.

5. **Read-only runtime and database checks**
   - Validate config YAML/JSON parsing, guardian health, bounded snapshot count, gateway status, scheduler status, provider/MCP connectivity, and current Postgres facts.
   - Inspect table columns before writing ad-hoc safety queries; do not assume JSON fields live in a generic `metadata` column. Wolfy recommendation safety data may be in `notes` JSONB.
   - Exclude synthetic tickers/far-future fixture dates when reporting production freshness. A raw `max(dt)` can be dominated by test fixtures.
   - Check recent run failures, price/feature row parity and dates, deterministic signals, and safety invariants such as no broker orders or live execution.

6. **Prove smoke tests do not mutate coordination state**
   - For context helpers, use their explicit smoke mode.
   - Capture `agent_runs.status='started'` and `agent_tasks.status='in_progress'` counts before and after.
   - A healthy budget-blocked smoke should end with `{"wakeAgent": false, "reason": "budget"}` and leave both counts unchanged.

7. **Avoid accidental live work during review**
   - Do not invoke a live bounded backfill, ingest runner, scanner, or recommendation writer merely as a status probe.
   - Prefer CLI status, cron history, logs, and read-only SQL. If a live runner is intentionally exercised, state that it mutates operational data, capture before/after rows, and verify the exact ticker/run side effects.

## Interpreting findings

Classify outcomes separately:

- **Regression:** a new failure causally tied to the cleanup/change.
- **Harness error:** wrong cwd, interpreter, schema assumption, or test discovery scope; correct and rerun.
- **Pre-existing baseline warning:** unrelated dirty-tree whitespace, optional credentials, build-only advisories, budget caps, or storage thresholds.
- **Healthy gate:** intentional budget/no-agent silence, zero recommendations, or no setup when governance gates block action.

The final report should list concrete tests and runtime facts, then give a clear PASS/FAIL verdict. Do not bury unrelated baseline warnings inside the regression verdict.
