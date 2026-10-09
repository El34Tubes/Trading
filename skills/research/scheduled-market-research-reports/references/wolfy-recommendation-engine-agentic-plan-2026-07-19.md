# Wolfy recommendation-engine agentic plan — 2026-07-19

Use this reference when the user asks to "start getting recommendations", "go for recommendations", or wire Wolfy into an agentic loop that can progress toward paper-trade candidates.

## Session learning

The right optimization target is not more scanner activity. It is the approved-strategy-gated recommendation pipeline:

1. Build one narrow deterministic EOD setup first: `liquid_pullback_continuation`.
2. Keep the strategy `research_only` by default.
3. Generate deterministic signals from `prices` + `features`; the LLM may explain/rank but not invent numbers.
4. Restrict v1 to liquid, high-quality universe slices (`blue_chip`, `etf_core`, liquid `large_cap`) instead of broad small-cap/long-tail expansion.
5. Harden validation before promotion: minimum IS/OOS trade counts, conservative slippage/costs, max-drawdown/turnover sanity, and explicit failure reasons.
6. If validation passes, promote at most to `candidate`; do **not** mark `approved` without explicit user approval.
7. Only an `approved` strategy may create actionable/paper recommendation rows from deterministic `signals`/`setups`.
8. Sentinel/Yang review gates and explicit human paper-acceptance must sit after setup generation and before `paper_trades` creation.
9. Make the loop visible in `visible_progress_ledger.py`: strategy status, latest signal counts, validation verdict, setup/recommendation counts, and next blocked gate.

## Concrete artifacts created in this session

- Plan file: `/root/.hermes/wolfy/RECOMMENDATION_ENGINE_AGENTIC_PLAN.md`
- Optimizer ledger updated: `/root/.hermes/wolfy/optimization_todo.md`
- Postgres `agent_tasks` created and dependency-chained:
  - `3577`: seed `liquid_pullback_continuation` as `research_only`
  - `3578`: deterministic pullback signal generator
  - `3579`: liquid v1 universe gate
  - `3580`: OOS validation hardening
  - `3581`: validation run / candidate decision
  - `3582`: approved-gated recommendation writer
  - `3583`: Sentinel/Yang review integration
  - `3584`: paper-ledger human-acceptance gate
  - `3585`: visible ledger recommendation-engine section

## Preferred user-facing framing

When reporting this path, be direct:

- "Your approval here authorizes building the recommendation engine, not approving a strategy."
- "Candidate is not approved."
- "No live trading or auto-execution."
- "The next human approval checkpoint is explicit: approve `liquid_pullback_continuation` for paper-trade recommendation generation only."

## Plan shape to reuse

The plan should be saved as a durable markdown artifact and then converted into ordered `agent_tasks` with stable fingerprints. Dependencies should be linear unless tasks can safely run in parallel. For recommendation readiness, linear sequencing is safest:

`seed strategy -> generate signals -> restrict universe -> harden validation -> run validation -> approved-gated recommendation writer -> Sentinel/Yang review -> paper-ledger human gate -> visible ledger`

## Pitfall avoided

Do not treat "go for recommendations" as permission to set `strategies.status='approved'` or create trade recommendations immediately. It means build the deterministic path to recommendations and bring the user an explicit approve/reject checkpoint after validation evidence exists.