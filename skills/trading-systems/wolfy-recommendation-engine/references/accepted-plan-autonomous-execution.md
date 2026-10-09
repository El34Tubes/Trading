# Executing an Accepted Multi-Phase Wolfy Plan

Use this when the user accepts the recommended defaults and asks for autonomous execution until completion.

## Acceptance semantics

- Treat “use all recommended defaults” as approval of defaults explicitly documented in the accepted plan.
- Record accepted defaults in the tracked plan or a decision ledger before implementation.
- This does **not** authorize live trading, broker writes, removal of fail-closed gates, destructive workspace cleanup, or unbounded provider spending.
- A default that depends on unavailable paid/licensed data remains blocked or uses the plan’s documented safe fallback.

## Durable start sequence

1. Read the saved plan and enumerate every task in the session task ledger; keep exactly one task `in_progress`.
2. Hash or otherwise record the original dirty workspace status.
3. Fetch without resetting and create a dedicated branch/worktree from the explicitly selected base.
4. Copy the accepted plan into the worktree and commit it as the implementation baseline.
5. Verify the original workspace status hash is unchanged.
6. Build the isolated Postgres test harness before running DB-integrated implementation loops.

## Per-task loop

For each task:

1. RED: add one focused failing behavioral test and run it to prove the expected failure.
2. GREEN: implement the smallest production change and rerun focused tests.
3. Run relevant integration tests only against the dedicated test database.
4. Perform spec review, then code-quality/security review; reviews are snapshot-specific.
5. Stage only reviewed task files, run diff/secret checks, and commit a bounded checkpoint.
6. Mark the task complete and move exactly one next task to `in_progress`.
7. Persist enough state in Git/plan/task ledger that a disconnected session can resume by inspection rather than memory.

Tasks that modify shared schema or shared orchestration files must be serialized. Parallelize only genuinely independent read/research or disjoint-file tasks.

## Timed-out agents and revision gates

A background implementation timeout is not proof that its work failed. Before restarting or discarding anything, inspect the isolated worktree and run the focused tests. If the requested files exist and focused tests are green, complete the full verification and bounded commit directly. If tests remain red, dispatch a fresh continuation containing only the exact failures and remaining acceptance criteria.

Keep specification review and code-quality review snapshot-specific. Use a maximum of three revision cycles per gate. If the third reviewed revision still has a blocker, preserve the branch and escalate to the user with a recommended correction, pause option, and explicit-risk option. Apply an additional revision only after the user authorizes that exception.

For Postgres ledgers and migrations, include adversarial direct-SQL and populated-partial-schema tests before review; helper-level API tests and clean-bootstrap tests alone repeatedly miss authoritative database bypasses.

## Release ordering

1. Finish all implementation and shadow gates.
2. Run isolated full tests and migrations.
3. Complete independent final review of the exact staged snapshot.
4. Commit/push the reviewed branch.
5. Only after reviewers/tests are finished, run a serialized scoped paper-only canary against production.
6. Read back both Git remote state and Postgres recommendation/governance state.

Never run production validation concurrently with integration tests or reviewer probes. Never call a background task “complete” merely because it was dispatched; completion requires returned evidence and read-back verification.
