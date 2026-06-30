# Wolfy candidate-validation gate pattern

Use when the user approves validation or cleanup priorities for Wolfy strategies/recommendations.

## Candidate validation sequence

1. Run deterministic validation first; do not ask the LLM to bless a strategy from summary metrics alone.
2. Promotion boundary:
   - `research_only -> candidate` may be automated by a passing validation rule.
   - `candidate -> approved` requires explicit human strategy approval.
   - No capital-ready setup exists without an `approved` strategy plus deterministic setup/risk rows.
3. Report both pass metrics and disqualifying/caution metrics.
   - If OOS Sharpe passes but in-sample Sharpe is weak, drawdown is extreme, turnover is high, or setup rows are absent, state that plainly.
   - Do not let a good OOS headline become a paper-trade recommendation.
4. Keep repaired recommendations watch-only when provenance is smoke/test data or when the approved-strategy gate is missing.
5. Backlog hygiene may expire stale pre-approved-strategy alpha review tasks, but the summary must say they were superseded by the EOD approved-strategy gate, not analytically resolved.

## Suggested wording

"This is candidate evidence, not approval. OOS survived, but the strategy still needs human review because [specific adverse metrics]. No trade authority or paper position was created."
