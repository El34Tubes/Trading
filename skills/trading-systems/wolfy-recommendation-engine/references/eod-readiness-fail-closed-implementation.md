# Fail-Closed EOD Readiness Implementation

Use this pattern when a deterministic EOD recommendation path must distinguish a complete no-signal session from incomplete data.

## Contract

- Resolve the intended signal date with a pinned/versioned NYSE calendar, including regular holidays and exceptional full-session closures. Weekend-only arithmetic is insufficient.
- Keep source modes explicit (`free_t_plus_1`, `paid_current_day`). Same-calendar-day data is not publishable until provider availability is explicitly verified.
- Require exact-date `prices` and `features` for the declared universe plus the benchmark. Return a typed result containing expected session, latest complete session, coverage numerator/denominator, deterministic missing-symbol list, source mode, and publishable flag.
- Gate before any external technical-data fetch, signal subprocess, recommendation writer, paper logger, or outcome mutation. Incomplete readiness returns a deterministic nonzero status and machine-readable `pipeline_incomplete` diagnostics; it never becomes clean `NO TRADE`.
- Treat explicit historical replay separately from the current-session path. Validate the exact requested date and never infer provider availability from today's state.
- Dry-run remains read-only but still executes and displays the readiness decision.

## TDD matrix

Cover:

1. weekday before/after close;
2. weekend to prior Friday;
3. regular NYSE holiday;
4. exceptional closure;
5. Monday pre-open resolving Friday under free T+1;
6. same-day unverified data blocked;
7. missing benchmark;
8. partial universe;
9. exact-date price with stale/missing feature;
10. future rows ignored;
11. out-of-range calendar date and naive datetime rejected;
12. current and replay orchestration both block before subprocess or recommendation side effects.

## Release verification

- Review the exact task commit/range, not merely the current worktree: identify the planned base and target commits, confirm whether later commits changed the task files, and compare only the task-owned files against the accepted plan.
- Run focused readiness/orchestration tests, then the dedicated-test-DB baseline.
- Compile every changed Python file and run `git diff --check`.
- Do not accept a hand-built or rule-generated exchange calendar merely because holiday fixtures pass. Differentially compare every supported date against an independent established NYSE calendar implementation, then add focused fixtures for each mismatch. At minimum, test the New Year's Saturday edge: NYSE is open on the preceding Friday (for example, 2021-12-31), unlike the usual federal observed-holiday rule.
- Exercise semantic adversarial probes beyond the authored tests: inspect the exact typed-result fields, verify the same-date readiness result in every source mode, test boundary dates, and assert blocked orchestration does not import/call downstream fetch or mutation paths.
- Capture production counts and approved-strategy authorization metadata through a read-only connection before and after tests; require literal equality.
- Independently review specification compliance first, then code quality/security. Passing authored tests is evidence, not proof of exact plan compliance; report a blocker whenever an external differential or adversarial probe contradicts the contract.

Observed implementation checkpoint (2026-09-05): Task 4 commit `60fd9bd` passed 16 focused tests but failed exact specification review. Differential comparison against `pandas_market_calendars==5.1.1` found 16 NYSE-session mismatches caused by applying Saturday New Year's observation to the preceding Friday; known historical examples include 1993-12-31, 1999-12-31, 2004-12-31, 2010-12-31, and 2021-12-31. The resolver consequently mapped Friday after-close and Monday pre-open to Thursday for those years. Treat this as a regression fixture and review lesson, not as current-state evidence; rerun against the current implementation and pinned reference before release.
