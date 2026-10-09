# Immutable Gate and Fail-Closed Revalidation

Use this reference when implementing or reviewing strategy approval, revalidation, demotion, or same-gate reactivation.

## Separate immutable authorization from latest performance

Store two distinct records:

- `approved_setup_outcome_gate`: immutable paper-authorization baseline.
- `latest_setup_outcome_gate`: newest performance result.

A failed run may overwrite only the latest result. It must not destroy the approved baseline, because a later run may recover only under that exact approved gate.

## Canonical approved-gate normalization

Authorization must require all of the following:

1. Gate and `thresholds` are JSON objects/mappings.
2. `passed` is the JSON/Python boolean `true`, not truthy text or a number.
3. `validation_mode` is explicitly present and exactly matches the supported evaluator.
4. `gate_definition_version` has exact integer type and supported value; reject booleans (`True == 1` in Python), floats, strings, missing values, and unknown versions.
5. Threshold keys exactly equal the canonical set. Do not use subset checks that silently discard unknown fields.
6. Integer thresholds reject booleans, fractional values, noncanonical strings, zero, and values outside their allowed range.
7. Decimal thresholds reject booleans, empty strings, malformed values, NaN, infinities, and out-of-range values.

If normalization fails, evaluation must produce a deterministic failed latest verdict rather than raising, falling back, or retaining approval.

## Explicit signal-parameter selection

Never select numeric parameters with truthiness chains such as `raw.get(key) or metadata.get(key) or default`.

Use key-presence precedence:

1. If the raw signal contains the key, validate that exact supplied value.
2. Else if strategy metadata contains the key, validate that value.
3. Else use the documented default.

An explicitly supplied invalid value is not missing. Reject it instead of replacing it. In particular:

- `target_r`: reject booleans, zero, empty/malformed/nonfinite values, and values outside the approved range.
- `max_hold_days`: reject booleans, zero, fractions, noncanonical strings, and values outside the approved range.
- `stop_rule`: reject unknown explicit rules; do not silently map them to a default evaluator.
- Signal `raw` and strategy metadata must be mappings; skip/fail closed on scalar/list JSON without aborting the whole cycle.

## Monthly-selection safety

Do not prefilter malformed approved gates out of the safety cycle. That creates a bypass where a fresh approved strategy with `latest_oos_verdict=true` remains approved indefinitely because neither revalidation nor stale/failed demotion sees it.

Monthly governance should:

1. Route every governed `approved` strategy through strict Python normalization, regardless of freshness or gate validity.
2. Allow `candidate` selection only when preliminary authorization metadata is canonical enough to justify a retry.
3. Stamp invalid approved definitions with a failed latest verdict.
4. Demote after revalidation, not before.
5. Require both a passing fresh gate and intact paper-only authorization to retain or restore approval.

Avoid direct SQL casts such as `(metadata->>'passed')::boolean` on untrusted JSON. Compare exact JSON booleans (`... = 'true'::jsonb`) and let all other shapes remain non-authorizing.

## Regression matrix

At minimum test:

- approved → failed/demoted → later same-gate pass/reactivation;
- missing, conflicting, boolean, or unknown evaluator version;
- missing and extra threshold keys;
- boolean/fractional integer thresholds;
- malformed/non-object metadata, thresholds, and signal raw JSON;
- explicit zero, false, empty, fractional, nonfinite, malformed, and out-of-range signal parameters;
- a fresh approved strategy with true prior verdict plus invalid gate metadata is still revalidated and demoted;
- signal subprocess failure prevents recommendation writer/logger/outcome-review lifecycle;
- no broker/live execution path is introduced.

## Live-database concurrency and final-state restoration

Wolfy integration tests and independent reviewer probes may execute against the live Postgres database. Treat a review as a potential database writer even when its requested task is "read/review the staged diff": a reviewer may run integration tests or direct revalidation probes.

Never run these concurrently:

- the full DB-integrated test suite;
- independent staged-snapshot reviews that may execute tests/probes;
- canonical live strategy revalidation or recommendation-state verification.

A concurrent test/reviewer transaction can finish after the live smoke and overwrite `last_validated`, `validated_through`, latest gate observations, backtest rows, or research-log state with an older fixture cutoff. Source tests may all pass while the final production row is stale.

Release order must be serial:

1. Finish all focused/full tests.
2. Stage and complete all independent reviews.
3. Commit and push the passing snapshot.
4. Only after reviewers are finished, run the canonical scoped live revalidation.
5. Open a new connection and read back strategy status, `last_validated`, `validated_through`, gate identity/version, latest verdict, recommendation counts, paper positions, and broker/live flags.
6. Compare `HEAD` with `origin/main` and confirm no staged/unstaged target-file changes.

If dates or samples unexpectedly regress, inspect recent `research_log` entries for repeated revalidation probes and their `validated_through` values. Restore state by rerunning the canonical scoped paper-only validation serially; do not fabricate or merely rewrite dates.

## Release verification

Independent review is snapshot-specific. After every reviewer-driven edit:

1. rerun focused tests, full suite, lint, and compilation;
2. restage only intended files;
3. run staged diff and secret/static checks;
4. verify no unstaged differences exist in reviewed files;
5. request a new independent review of that exact staged snapshot;
6. commit and push only after the exact snapshot passes.
