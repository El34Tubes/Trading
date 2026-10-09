# Governed Strategy Revalidation

Use this pattern when an approved paper strategy must be periodically revalidated and may be demoted or reactivated without silently changing its approval contract.

## Separate immutable approval from mutable observations

Persist two distinct records:

- `approved_setup_outcome_gate`: immutable evidence and thresholds that the user approved for paper-only use.
- `latest_setup_outcome_gate`: mutable result from the newest revalidation.

Never overwrite the only passing approval record with a failed latest result. Authorization and “same-gate” thresholds must come from `approved_setup_outcome_gate`; reporting and current verdicts come from `latest_setup_outcome_gate`.

For legacy rows with only a passing `latest_setup_outcome_gate`, migrate/seed that object into `approved_setup_outcome_gate` before writing a new result. Do not seed from a failed latest result.

## Prove exact same-gate identity

A boolean `passed=true` is not a sufficient approval contract. Normalize and preserve a complete immutable definition containing:

- evaluator/validation mode;
- gate-definition version;
- every threshold field (`min_sample`, `min_oos_sample`, `min_hit_rate`, `min_oos_hit_rate`, `max_stop_rate`, `min_median_mfe_r`, and `oos_fraction`).

Require all fields, parse numeric values, reject non-finite/out-of-range values, and fail closed when any field is absent. Require the threshold object’s key set to equal the canonical approved set exactly; a required-key subset check is insufficient because unknown keys would be silently discarded and the stored definition would not be canonical. Parse integer gate counts as strict canonical integers: reject booleans, fractions/floats, leading-zero strings, and other coercible-but-noncanonical forms rather than using `int(value)`. For identity/version fields, require the exact expected type as well as value (`type(version) is int` before comparing to `1`), because Python booleans are integers and `True == 1`. Authorization requires the evaluator identity fields to be explicitly present and supported. If legacy data must be migrated, perform a separate audited migration that seeds the immutable approval record without reactivating a strategy; revalidation itself must never infer authorization from an unversioned latest result. Reject a conflicting evaluator mode or unsupported version rather than silently relabeling it. Every later revalidation must evaluate with this immutable normalized definition; store the newest observed result separately and stamp that result with the evaluator mode/version. If the immutable definition is invalid, force the current verdict to failed even for an already-approved strategy so monthly governance can demote it; merely blocking candidate reactivation is insufficient.

## Monthly lifecycle

1. Select the **governance population** from paper-governance metadata, status, scope, and scheduling state without requiring the stored immutable gate to be valid. Gate validity is an outcome of normalization, not a safe SQL prefilter.
2. Normalize each immutable gate inside the fail-closed revalidation path.
   - A valid passing immutable gate permits evaluation and may authorize candidate reactivation.
   - A malformed, missing, unsupported, or noncanonical definition must stamp the current verdict failed, including for a fresh already-approved row.
3. Revalidate before applying stale/failure demotion.
4. If the latest gate passes:
   - keep an approved strategy approved;
   - reactivate a candidate only when the immutable approval predicate is complete.
5. If it fails, record the failure and demote an approved strategy to candidate.
6. Keep a valid immutable approval gate intact across ordinary observed failures so later data can pass the same thresholds and reactivate the candidate. Do not rewrite a malformed gate into an apparently valid approval record.

Candidate eligibility must use the immutable approval gate, not `latest_setup_outcome_gate`; otherwise the first failure permanently prevents later recovery.

### Selection-bypass pitfall

Do not write a refresh query that requires the expected gate version, required threshold keys, or `approved_gate.passed=true` and then assume the Python normalizer will fail malformed definitions. Rows rejected by that SQL never reach the normalizer. A fresh approved row with `latest_oos_verdict=true` can therefore remain approved indefinitely after gate metadata corruption and can continue feeding a recommendation writer that checks only status and paper-only flags.

Use one of these safe shapes:

- select governed approved rows (and reactivation-eligible candidates) broadly, normalize in Python, and stamp invalid definitions failed before demotion; or
- add a separate explicit invalid-definition scan/demotion path that covers fresh approved rows as well as stale rows.

Regression test the bypass directly: create a fresh approved strategy with a currently passing verdict, corrupt or omit the immutable gate version/threshold container, run monthly governance, and assert `latest_oos_verdict=false`, candidate status, no reactivation, and no downstream recommendation eligibility.

## Provenance dates

Store separate dates:

- `validation_run_date`: when governance ran; use for staleness scheduling.
- `validated_through`: latest stored market-data date actually included; derive from relevant strategy signal tickers and cap at the requested as-of date.

Never label validation as covering the wall-clock date when the newest EOD bar is earlier.

## Fail-closed signal metadata

Before evaluating future bars, parse and validate entry, stop, target multiple, and holding horizon. Reject malformed, non-finite, or out-of-range values rather than coercing them into easy targets or unsafe SQL limits. A practical bounded default is:

- entry and stop finite and positive;
- stop below long entry;
- `0 < target_r <= 10`;
- `1 <= max_hold_days <= 60`.

**Missing is not the same as invalid.** Select configuration by key presence, not truthiness. A fallback may apply only when a key is absent from both signal and strategy metadata. If an explicit value is `0`, `false`, `null`, an empty string, `NaN`, or infinity, reject the signal; never let Python `or` replace it with a permissive default.

Parse holding horizons as strict canonical integers. Reject booleans, floats/fractions (including `1.5`), nonnumeric strings, leading-zero/noncanonical strings such as `"01"`, and values outside the bound. Do not use `int(value)` as validation because it silently truncates floats. Parse target multiples separately and reject booleans, non-finite decimals, zero/negative values, and values above the approved bound.

Invalid or incomplete immutable gate thresholds also fail closed: they cannot authorize reactivation and must not be fed directly into the evaluator where they could crash governance or weaken thresholds. Use a conservative non-authorizing evaluation configuration for diagnostics, or skip evaluation with an explicit invalid-gate result.

Treat every JSON/JSONB container as untrusted input. Check that strategy metadata, approved/latest gates, threshold objects, and signal payloads are mappings before copying with `dict()`; scalars and arrays must become an invalid gate or skipped signal, not a batch exception. In SQL authorization predicates, compare JSON values exactly (for example, JSON boolean `true`) rather than casting arbitrary `->>` text to boolean. Require the explicit immutable approved gate in selection queries—do not `coalesce` to a mutable latest gate.

Require signal `raw` metadata to be a JSON object/mapping before converting or reading it; skip scalars, arrays, and other shapes without aborting the batch. Treat rule fields as closed enums: an absent stop rule may use the documented default, but an explicitly unknown or wrong-typed stop rule must be rejected rather than silently mapped to intrabar behavior.

Skipped invalid signals should not count toward sample size.

## Production-safe tests

Never run an unscoped monthly revalidation test against a production database. Add an explicit `strategy_names`/strategy-ID scope and apply it to both refresh and demotion queries. Use synthetic strategy names, tickers, and dates; clean dependent rows in foreign-key order.

Required regression sequence:

1. Start with an explicitly approved strategy and immutable passing gate.
2. Add data that fails the gate; run monthly governance and assert demotion to candidate.
3. Assert latest gate failed while immutable approval gate remains passing.
4. Add later data that makes the same thresholds pass.
5. Run governance again and assert authorized reactivation.

Also test malformed negative targets/invalid horizons produce sample size zero and no activation.

## Orchestration safety

After signal generation succeeds, run the paper lifecycle in order: recommendation writer, paper logger, then outcome reviewer. Stop immediately on signal-generation failure. Scope by signal date/tickers, return explicit `broker_orders_created=0`, and assert no live-order API is reachable from this chain.
