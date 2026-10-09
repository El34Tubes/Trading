# Long-Running Delegation Checkpointing

Use this pattern when a coding task combines substantial implementation, database migration work, exhaustive tests, static checks, and a commit. A single delegation can finish the code but time out before verification/reporting, producing a misleading `timeout` status.

## Split the work before dispatch

Prefer two bounded stages when the task is likely to approach the delegation runtime limit:

1. **Implementation stage**
   - Read only the named task/spec.
   - Write RED tests.
   - Implement until the focused suite is GREEN.
   - Run `git diff --check`.
   - Leave changes uncommitted and report exact remaining checks.

2. **Release stage**
   - Independently inspect the worktree and focused result.
   - Run the full suite, schema/migration idempotency, lint/compile, static scans, and immutable-state comparisons.
   - Stage an explicit file list and commit only after all gates pass.

Do not ask one leaf agent to implement a large schema, run hundreds of tests, conduct security scans, compare production state, stage, commit, and produce a detailed report if those steps are likely to exceed its hard runtime.

## Recover from a timeout

Treat `timeout` as “no trustworthy summary,” not “no useful work”:

1. Check branch, `HEAD`, index, worktree status, diff stat, and diff check.
2. Run the narrowest focused test yourself.
3. If focused GREEN, perform only the mechanical release stage; do not re-dispatch the whole implementation.
4. If focused RED, pass the exact failures and current files to a fresh agent with one missing function or invariant as its bounded goal.
5. If a second timeout occurs, stop issuing broad prompts. Split by API, migration invariant, or verification phase.

## Review-loop discipline

- Specification review precedes quality review.
- Each review is tied to an exact clean commit.
- A later edit invalidates the prior verdict.
- Reviewers should use adversarial probes, not only rerun authored tests.
- After the configured revision cap, use an escalation gate; if the user approves another revision, make it narrow and declare it the final requested review cycle.

## Evidence to preserve

For every checkpoint, retain:

- focused RED/GREEN counts;
- exact commit or explicit “uncommitted” state;
- intended file list;
- full-suite scope and count;
- immutable external-state fingerprint before/after;
- exact review snapshot and verdict.
