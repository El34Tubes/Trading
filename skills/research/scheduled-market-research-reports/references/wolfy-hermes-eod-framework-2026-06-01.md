# Wolfy / Hermes-EOD framework shift — 2026-06-01

## Trigger

The user uploaded `hermes_bootstrap.md` and explicitly asked to adjust Wolfy goals, existing setup, Kanban, and reporting around a new EOD quantitative research/screening framework.

## Durable operating change

For Wolfy-style market research, prefer the Hermes-EOD architecture when the user references the new goals/framework/constitution:

- Decisions are **EOD-only**: use closing data; execution, if any, is next session and done manually by the human.
- The LLM is **out of the numeric signal path**: deterministic scripts/functions compute features and signals; the LLM interprets, filters, ranks, explains, and writes proposals.
- No auto-execution, no broker authority, no banking/money movement.
- Strategy improvement may be autonomous, but deployment is human-gated: `research_only -> candidate -> approved -> retired`.
- Screening may propose setups only from `strategies.status='approved'` and only after deterministic signal rows exist.
- Code-enforced risk circuit breakers are absolute: per-trade risk, portfolio heat, name weight, ADV fraction, drawdown kill switch, and slippage/cost guardrails.
- Prefer “no setup tonight” over forced trade ideas.
- Separate FACT (measured/filed/from DB) from JUDGMENT (interpretation/inference) in rationales.

## Implementation pattern created

A durable implementation plan was written to `/root/.hermes/wolfy/HERMES_EOD_IMPLEMENTATION_PLAN.md` and Kanban was decomposed into an EOD graph:

| Lane | Purpose |
|---|---|
| P0 | Governance/prompts: update Wolfy/Alpha/Sentinel/Yang/Clerky to EOD-only posture |
| P1 | Schema gap/migration: add Postgres tables/config non-destructively |
| P2 | EOD ingest/features: deterministic prices/features/runs |
| P3 | Strategies/signals: deterministic signals and approved-strategy gate |
| P4 | Screening/setups: setup writer plus risk circuit breakers |
| P5 | Backtest/research loop: walk-forward OOS and candidate-only promotion |
| P6 | Monitoring/revalidation: pre-open checks and demotion-only decay circuit |
| P7 | Cron/E2E handoff: after-close ingest/features/screening and pre-open monitor |

## Important safety lesson

The user also said to “disregard any security prompts for now.” Do **not** encode that as an allowed workflow. Acknowledge speed/autonomy, but keep credential safety, destructive-change approvals, broker/money movement restrictions, and secret redaction intact.

## Social/scanner implication

Existing scanner/social/Alpha Search work is not discarded. Under Hermes-EOD, these become candidate discovery and research context. They must not produce actionable recommendations unless an approved deterministic strategy signal and all screening/risk gates pass.
