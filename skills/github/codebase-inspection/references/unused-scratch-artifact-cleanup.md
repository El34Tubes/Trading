# Cleaning unused scratch artifacts safely

Use when a repo has accumulated untracked one-off scripts, generated payloads, downloaded artifacts, or local backups, especially in a live operations repo where production scripts and tests coexist with ad-hoc investigation files.

## Pattern

1. Start from Git truth, not filenames alone:

```bash
git status --porcelain=v1 -z
```

Only remove untracked files unless the user explicitly asks to delete tracked code. Tracked modifications may be real work in progress.

2. Classify untracked entries into buckets:

- production-looking scripts/tests/wrappers to keep and possibly commit
- generated payloads/downloads/cache/output to delete or ignore
- one-off probe/inspect/query/verify scripts to delete if not referenced
- skill/reference/docs to keep unless they are curator backups or generated noise

3. Before deleting, check for references when the filename could be imported or called:

```bash
git grep -n "name_or_pattern" -- .
```

4. Delete only conservative categories first. Good candidates:

- `tmp_*`, `*.out`, downloaded `.html/.xml/.txt/.json` payloads
- browser scrape bundles or generated page scripts
- one-off `probe_*`, `inspect_*`, `query_*`, `verify_*` files when untracked and not referenced
- local curator backup directories when not meant for version control

5. Patch `.gitignore` immediately for recurring generated patterns so the cleanup persists.

6. Stage and run checks before committing:

```bash
git add -A
git diff --cached --check
```

Then run the smallest meaningful test subset for the affected area. If test dependencies are missing in the system Python, use `uvx --from pytest --with <needed-deps> pytest ...` rather than installing globally.

7. Commit and push if the user's workflow expects the operations snapshot in Git.

## Pitfalls

- Do not delete tracked files as "unused" without deeper reference analysis and user approval.
- In an operations repo, untracked profile wrappers and cron scripts may be live even if recently created; do not remove them just because they were untracked.
- Avoid committing transient cron timestamp churn separately unless it remains the only dirty file after the main commit and the repo policy expects a complete clean snapshot.
- `git diff --cached --check` can catch trailing whitespace in unrelated staged skill edits; fix before committing.
