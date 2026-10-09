# Tracked live-repository preservation audit

Use this when a live Hermes/Wolfy home is also a Git repository and the user wants to preserve durable source/config without committing runtime churn.

## Snapshot and scope

1. Record `HEAD`, `git status --short`, `git diff --name-status HEAD`, and file counts at the start.
2. Distinguish tracked modifications, staged additions, unstaged changes, untracked files, and ignored files. `git diff HEAD` does not include ordinary untracked files.
3. Recheck status before reporting. A scheduler, curator, autorepair job, or another worker may stage or rewrite files during the audit. If scope changed, report both snapshots and do not imply the reviewer caused it.
4. Do not modify files or stage/reset anything during a review-only request.

## Classify by durability

**Preserve as source/config:** production Python/SQL/tests, stable wrappers, deliberate config policy, cron definitions, accepted plans, skill content/references, `.bundled_manifest` when synchronized with bundled files, and `.hub/lock.json` as installation provenance.

**Exclude as runtime telemetry/churn:** `.usage.json`, generated skill prompt snapshots, session/log/cache/database files, cron counters and last/next-run timestamps, last status/error fields, and transient scheduler timestamps.

**Review before preserving:** one-off `query_*`, `insert_*`, `validate_*`, temporary task-ID scripts, downloaded source evidence, paste payloads, and generated reports. Preserve only when they are reusable migrations/tests or intentional research evidence; otherwise archive privately or ignore them.

For monolithic files such as `cron/jobs.json`, classify fields rather than blindly classifying the whole file. Preserve job identity, schedule, script/prompt, no-agent mode, intentional enable/pause state, toolsets, and delivery policy. Exclude execution counters/timestamps/errors and sanitize routing identities before publishing.

## Security checks

- Treat `approvals.mode: false` as Hermes approval mode `off`; YAML parses bare `off` as `False`, and Hermes intentionally normalizes that value to approval bypass. Flag a change from `manual` to false/off as blocking unless explicitly authorized.
- Review related confirmation toggles and dangerous allowlist entries together; their combined effect matters.
- Scan added/current content for credentials without printing matched values. Distinguish real secrets from documentation placeholders, redaction markers, and credential-extraction examples before reporting.
- Flag newly published chat/user IDs, internal hosts, or routing metadata as privacy/operational exposure even when they are not authentication secrets.

## Wolfy SQL migration checks

A textual rename inside `CREATE TABLE IF NOT EXISTS` is not a migration. For every renamed column:

1. Compare clean-bootstrap definitions, populated-schema `ALTER` migrations, views, triggers, writers, compatibility sync scripts, and tests.
2. Search both old and new names across the whole Wolfy tree.
3. Ensure existing populated tables are migrated explicitly and fresh bootstrap uses the same canonical name.
4. Verify compatibility views expose old aliases deliberately instead of referencing a column that bootstrap never creates.
5. Guard casts from JSON/text with shape or numeric validation; `NULLIF(value, '')::integer` still aborts on nonempty malformed values.

A mixed `sqlite_id`/`legacy_id` tree is a release blocker when fresh schema, existing schema, views, and compatibility writers disagree.

## Test-isolation checks

- A test that passes a temporary SQLite path is not isolated if status/count helpers still open the default Postgres DSN.
- Trace every helper invoked by the test, including count, freshness, dual-write, and compatibility helpers.
- Prefer AST/JSON/YAML parsing for non-mutating validation. For pytest in a review-only workspace, use `PYTHONDONTWRITEBYTECODE=1` and disable the pytest cache provider to avoid repository churn.
- Do not run DB-integrated tests until their DSN and rollback boundary are proven safe.

## Reporting format

Lead with blocking findings using `file:line`, impact, and preserve/exclude disposition. Then give a category table covering all changed classes. State exactly what was verified (parse counts, focused test results, diff checks, secret-scan result) and what was intentionally not run. Never call the tree release-ready when a source/config blocker remains.