# Tracked Python obsolescence audit

Use this procedure when deciding whether tracked Wolfy Python files are safe deletion candidates. Treat absence of imports as insufficient: many production entry points are invoked by Hermes cron through stable global/profile wrappers.

## Evidence hierarchy

1. Inventory tracked code with `git ls-files 'wolfy/*.py' 'wolfy/**/*.py'`; distinguish tracked files already deleted in the dirty worktree from present files.
2. Parse Python imports (AST is preferable to text-only matching), separating production importers from test-only importers.
3. Search the whole repository for both the filename and module stem. Include documentation only as secondary evidence.
4. Inspect live `cron/jobs.json`: script basename, enabled state, last status/run, and profile. A successful recent cron run is strong retention evidence.
5. Inspect `/root/.hermes/scripts/` and `/root/.hermes/profiles/*/scripts/`. Stable wrappers may import Wolfy modules after modifying `sys.path`; modules with no cron basename can still be production-critical.
6. Hash duplicate scripts across Wolfy/global/profile locations. Exact duplicates are not automatically redundant when wrapper synchronization or profile isolation is intentional.
7. Inspect `git log --follow` and `git blame`. One-commit migration utilities with no runtime references are stronger candidates than maintained modules.
8. Look for completion artifacts such as idempotent migration manifests. A final zero-change rerun is strong evidence that a one-shot migration has completed.
9. Review dirty-tree deletions but do not assume they are authorized or correct. Report them as pre-existing state and do not modify them during an audit.

## Classification rules

### High-confidence deletion candidate

Require converging evidence: no production imports, no active cron, no global/profile wrapper, no allowlist/control-plane dependency, no current manual workflow, and history indicating a one-shot or retired implementation. State residual documentation cleanup and operational risk.

### Suspicious but retain

Retain when any direct runtime edge remains, including:

- active cron basename or recent successful run;
- import by a stable wrapper;
- test-only import that provides meaningful safety/regression coverage;
- autorepair/synchronization management;
- operator allowlist or documented manual control-plane purpose;
- a stale-looking constant/helper that still points at the file (delete only as a coordinated refactor with tests).

## Wolfy-specific pitfalls

- Postgres-only policy makes SQLite migration/bootstrap scripts suspicious, but deletion must wait if another tracked module still directly references their path.
- Fixture/SQLite smoke runners may remain valuable even after live SQLite retirement; do not confuse test isolation with a live fallback.
- Cron-facing scripts often live under `/root/.hermes/scripts/`, while reusable logic lives under `/root/.hermes/wolfy/`. Search both layers.
- Exclude untracked scratch files when the request is specifically about tracked scripts.
- Report only high-confidence candidates; omit weak guesses rather than inflating the list.
