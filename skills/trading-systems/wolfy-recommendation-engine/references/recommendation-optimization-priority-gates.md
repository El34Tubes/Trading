# Recommendation Optimization Priority Gates

Use this decision sequence when asked whether Wolfy needs more data, another strategy, or a model.

## 1. Classify the data bottleneck precisely

Do not treat all “more data” as one category.

- **Historical depth incomplete:** active targets still lack the declared validation depth and are neither current-short nor recorded provider-unavailable. Finish bounded backfill first.
- **Historical depth complete, daily freshness incomplete:** stop broad history pulls. Fix expected-session resolution, bounded T+1 catch-up, exact-date price/feature parity, and fail-closed publication.
- **Daily freshness complete, event/security provenance incomplete:** populate earnings/event vetoes, corporate-action identity, source provenance, and point-in-time security eligibility before expanding alpha.
- **All readiness gates complete:** expansion/strategy research can begin.

Require one accounting equation for historical completion:

```text
targets = depth_ready + current_short + recorded_unavailable + eligible_remaining
```

Completion requires `eligible_remaining=0`, feature-date parity, and a zero-batch rerun. Provider-limited symbols may remain active for incremental daily ingestion while only repeated historical backfill is disabled with evidence.

## 2. Increase opportunity without changing alpha

Before changing a validated strategy:

1. Preserve its exact predicates and outcome semantics.
2. Add golden-parity tests on the original production universe and historical dates.
3. Build a source-backed U.S./liquidity/security-identity policy.
4. Expand through shadow caps such as 100 → 200 → 300.
5. Require complete-session coverage and deterministic reruns at each cap.
6. Keep a global max-three allocator and no-forced-trade behavior.

This usually increases legitimate opportunity frequency with less overfitting risk than relaxing thresholds.

## 3. Instrument gate attrition before tuning

Persist one deterministic pass/fail evaluation per run, ticker, and strategy. Record all failed gates plus one canonical terminal reason. Aggregate near misses over multiple horizons.

Do not automatically tune from near misses. Use attrition to predeclare a hypothesis and test it under walk-forward and multiple-testing controls.

## 4. Add orthogonal setup families before ML

Prefer an economically distinct deterministic setup, such as trend pullback/reclaim, over a threshold-relaxed clone of an approved breakout. New families remain research-only until governed historical validation, adequate forward observations, and explicit approval.

Use ML only after complete daily ledgers and meaningful forward outcomes exist. Appropriate later uses are ranking otherwise-valid candidates, regime-conditioned calibration, or option-expression choice. Deterministic eligibility, risk, approval, and no-trade gates remain authoritative.

## 5. Keep underlying and option evidence separate

Technical option features are not exact chain evaluations. For each final underlying qualifier, acquire an exact read-only chain and deterministically choose `long_call`, `call_debit_spread`, or `no_option`. Track option outcomes separately from underlying setup outcomes. Poor chain liquidity must not rewrite the underlying strategy’s edge.

## 6. Explicit bounded budget overrides

A hard budget gate remains an implementation stop by default. A general “implement this plan” instruction does not silently waive it.

If the user explicitly chooses a bounded interactive override:

1. Record the authorization and exact slice in the durable task/run metadata.
2. Do not raise or disable the global budget threshold.
3. Keep scheduled/background LLM jobs governed by the normal gate.
4. Use an isolated clean worktree and dedicated test database.
5. Limit the override to the named interactive slice.
6. Preserve strict TDD, independent spec review, code-quality review, and production invariant checks.
7. Stop again at any paid-source, live-trading, destructive-cleanup, or permanent-policy decision not separately authorized.

## 7. Recommended default ordering

```text
complete-session readiness
→ earnings/corporate-action/bar-quality provenance
→ security identity and controlled universe expansion
→ gate-attribution ledger
→ walk-forward / multiple-testing / survivorship controls
→ one orthogonal research setup
→ exact read-only option-chain decisions
→ explainable ranking model only after sufficient forward evidence
```
