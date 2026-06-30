# Operational JSON state-file edits

Use this when maintaining an operations repository that tracks live scheduler/config state such as `cron/jobs.json`.

## Pattern

1. Treat JSON state files as both configuration and volatile runtime state.
   - Prompt/config fields may be intentional source changes.
   - Fields like `last_run_at`, `next_run_at`, `repeat.completed`, and global `updated_at` may churn while you work.

2. Avoid rewriting the whole file with arbitrary key sorting.
   - Do not use `json.dumps(..., sort_keys=True)` on tracked operational state unless the repo already uses sorted keys.
   - Preserve existing job order and object key order where possible.
   - If you must parse/rewrite, reconstruct output in the prior file's order or use a targeted patch.

3. Keep diffs reviewable before committing.
   - Run `git diff --stat` and inspect the specific state file diff.
   - If a formatter caused massive reorder-only churn, rewrite/preserve order before staging.
   - Stage only intentional configuration/source changes; leave or revert incidental runtime counters unless the snapshot policy explicitly wants them.

4. Clean local tool telemetry noise.
   - Skill usage sidecars such as `skills/.usage.json` can be modified just by loading skills. Do not commit them unless the task explicitly concerns skill telemetry.
   - Reset or leave unstaged telemetry-only changes after the real commit.

5. Verification before finalizing.
   - Run the relevant focused tests/smoke commands.
   - Confirm `git rev-parse HEAD` equals `git rev-parse origin/main` after push when the user asked whether commits are happening.
