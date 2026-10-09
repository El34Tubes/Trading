# Recommendation Droughts and Strategy Pivots

Use this reference when a deterministic paper system produces too few actionable recommendations or the user wants to change strategy families.

## Diagnose delivery before changing gates

Classify each session as one of three outcomes:

1. **Verified no-trade:** expected market session is ready, declared universe coverage is complete, approved/authorized strategies ran, and no setup qualified.
2. **Governance-blocked:** deterministic signals exist, but their strategies are research-only, failed, stale, or otherwise unauthorized.
3. **Pipeline incomplete:** required data, deployment, chain acquisition, allocator, writer, scheduler, or delivery stage did not run or is not production-installed.

A reviewed branch is not a deployed strategy. Confirm all layers independently:

- strategy code is merged into the production revision;
- strategy seed exists with the intended status and version;
- current eligible universe and benchmark coverage are complete;
- deterministic signal generation ran for the expected session;
- read-only option-chain acquisition ran for qualifying signals;
- option evaluations/snapshots contain durable provenance;
- fallback policy is explicit when no safe option exists;
- allocator and every sibling writer share the same cap/risk contract;
- scheduled orchestration invokes the new path;
- concise delivery reads the new durable outputs;
- future-dated fixtures and test residue are excluded from operational “latest” queries.

Report the first broken layer. Do not call an incomplete pipeline a no-trade, and do not loosen strategy thresholds merely to hide missing deployment or data.

## Prefer a useful vertical slice

When governance work grows faster than recommendation delivery, stop adding horizontal features and finish one end-to-end slice:

`ready universe -> deterministic setup -> ranked allocation -> exact option selection -> permitted fallback -> paper ledger -> outcome ledger -> user delivery`

Keep safety controls, but prioritize a runnable production path over additional strategy variants. A system with many reviewed modules but no chain snapshots, scheduler, or production seed cannot issue options recommendations.

## Interview order for a strategy pivot

Ask only choices that materially change implementation, preferably one compact question at a time:

1. **Expression policy:** options-only/no-position on chain failure, underlying fallback, or advisory-only underlying.
2. **Universe:** asset class, capitalization range, price floor, dollar-volume floor, geography/security-type exclusions, benchmark-only instruments.
3. **Strategy sleeves:** preserve validated strategies; add new versioned sleeves rather than mutating approved formulas.
4. **Allocator:** globally ranked opportunities versus reserved sleeve quotas; sector/correlation limits.
5. **Risk mandate:** maximum concurrent positions, per-position defined risk, aggregate open risk, and whether account ruin is an accepted paper-test outcome.
6. **Release:** shadow universe/stages versus immediate broad paper rollout.

Record accepted choices in durable configuration and update every writer, allocator, summary, test, and policy document that carries old defaults.

## Freeze scope before autonomous execution

Complete the architecture-changing interview before dispatching a plan writer or overnight implementation loop. If the user answers while a background planner is still running, treat that planner's result as stale until reconciled:

1. Search the generated plan for every superseded sleeve, fallback, cap, universe, and rollout choice—not just the obvious task heading.
2. Remove obsolete tasks and repair task numbering, cross-references, release gates, definitions of done, and test commands.
3. Commit the corrected plan separately and require a clean worktree before the autonomous loop starts.
4. Give each loop tick one bounded next task, require RED/GREEN evidence and an exact commit/checkpoint, and forbid unrelated production changes.
5. Resume identifiable partial work; never let recurring workers restart the plan or overlap on a dirty tree.
6. Report only concrete progress, blockers, or completion. A scheduled loop is not evidence of delivery; Git commits and executed checks are.

This prevents a late user decision (for example, removing a rotation sleeve or changing three slots to twenty) from surviving in a long plan and being implemented overnight despite the conversational correction.

## Strategies that fit deterministic EOD agents

Strong fits have objective daily inputs, explicit invalidation, sufficient event frequency, low latency sensitivity, and auditable next-session execution:

- trend pullback and reclaim;
- volatility contraction followed by orderly breakout;
- close-confirmed breakout/continuation;
- cross-sectional or industry-relative-strength rotation;
- short-horizon mean reversion in established trends;
- post-earnings drift only with trustworthy point-in-time event provenance.

Poor fits for a delayed EOD stack include discretionary chart interpretation, current-news sentiment as the entry gate, 0DTE/intraday scalping, illiquid microcaps, and strategies requiring fabricated historical option chains.

## Multi-sleeve design

- Preserve an approved strategy unchanged while adding research-only versions/sleeves.
- Backtest underlying setup quality chronologically and collect exact option evidence forward.
- Rank all qualifying sleeves in one allocator unless the user explicitly requests quotas.
- Deduplicate correlated exposures and persist why each candidate won or lost allocation.
- When fallback is allowed, choose `long call`, `call debit spread`, `underlying`, or `no trade` deterministically. An options-only strategy must still reject the underlying; fallback belongs to a different explicit instrument policy.
- Track underlying and option outcomes separately.

## Risk contracts are configuration, not folklore

Never leave an old hard-coded cap (for example, three recommendations/day) after the user changes the mandate. A cap change must update:

- allocator configuration and durable run identity;
- every recommendation writer sharing capacity;
- transaction/advisory-lock key and cumulative-count logic;
- position sizing and aggregate-risk calculations;
- summaries and user-facing constraint text;
- repeated-call and concurrent mixed-writer tests;
- outcome metrics, including drawdown and ruin probability/events.

If the user accepts 100% aggregate paper risk, preserve that as an explicit experimental configuration—not as an implicit weakening of live-trading controls. Live execution remains independently disabled.

## Universe provenance

For capitalization-filtered systems, market cap and security classification are point-in-time inputs. Persist source, observed/available timestamps, eligibility version, and exclusion reason. Price and average-dollar-volume floors must be computed as of the decision session. Benchmarks may remain outside the tradable universe as context-only instruments.
