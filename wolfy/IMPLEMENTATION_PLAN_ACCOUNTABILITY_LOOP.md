# Wolfy Accountability Loop Implementation Plan

> **For Hermes:** Use Kanban workers plus the existing Wolfy cron/agent desk to implement this plan task-by-task. Do not wait for additional user prompts unless a card is explicitly blocked by credentials, provider limits, or a destructive action requiring approval.

**Goal:** Finish the implementation path from fresh scanner data to promoted recommendations, Sentinel review, paper-trade tracking, outcome grading, and end-to-end cron handoff.

**Architecture:** Keep SQLite `/root/.hermes/wolfy/wolfy.db` as live source of truth, Postgres `wolfy` for coordination/search/review ledgers, and existing cron jobs as the autonomous execution layer. Use deterministic scripts for data validation and state transitions; reserve LLM reasoning for synthesis/rationale only.

**Tech Stack:** Python, SQLite, PostgreSQL 16 + pgvector/pg_trgm, Hermes cron, Hermes Kanban, pytest/unittest.

---

## Current Verified State

- Recommendation logger/trade-ticket validator card `t_736821fa` was reviewed and accepted.
- Verification run: `/root/.hermes/wolfy/check_postgres_requirements.py` OK; focused pytest suite passed: `18 passed in 0.32s`.
- Existing downstream cards are now unblocked/available:
  - `t_b51dea08` — Sentinel review persistence/status updater.
  - `t_34c824e2` — Paper portfolio engine and outcome grader.
- Newly created priority cards:
  - `t_0957e926` — P1 scanner freshness gate before every report.
  - `t_f6c2ca0f` — P2 alpha lead to recommendation promotion gate.
  - `t_e2baadfd` — P3 wire promotion gate into twice-daily Wolfy report flow.
  - `t_3e5cd5eb` — P6 end-to-end accountability loop smoke test and cron handoff.

## Dependency Graph

```text
P1 scanner freshness gate: t_0957e926
  └── P2 lead promotion gate: t_f6c2ca0f
        └── P3 report-flow integration: t_e2baadfd

Recommendation logger accepted: t_736821fa [done]
  └── P4 Sentinel persistence: t_b51dea08
        └── P5 paper portfolio/outcome grader: t_34c824e2
              └── weekly scorecard: t_28f5a422 [existing]

P6 end-to-end verification: t_3e5cd5eb
  depends on: t_e2baadfd, t_b51dea08, t_34c824e2
```

## Task P1: Scanner Freshness Gate

**Objective:** Make stale market data impossible to use for actionable recommendations.

**Files likely touched:**
- Modify: `/root/.hermes/wolfy/wolfy_report_context.py`
- Modify or wrap: `/root/.hermes/wolfy/wolfy_scanner.py`
- Possibly modify: `/root/.hermes/scripts/wolfy_report_context.py`
- Test: create a focused scanner freshness test or smoke helper under `/root/.hermes/wolfy/`

**Acceptance criteria:**
1. `wolfy_scanner.py` runs before twice-daily report context or report context verifies a fresh run exists.
2. Latest scanner run metadata is printed in report context.
3. Stale scanner data blocks recommendations with explicit `scanner_stale/no-trade` language.
4. A smoke test proves latest-run selection and stale detection.
5. Existing cron `ba183091b5c0` benefits automatically.

**Verification commands:**
```bash
python /root/.hermes/wolfy/check_postgres_requirements.py
python /root/.hermes/wolfy/wolfy_scanner.py
python /root/.hermes/wolfy/wolfy_report_context.py
python -m pytest -q /root/.hermes/wolfy
```

## Task P2: Alpha Lead Promotion Gate

**Objective:** Convert qualified scanner/alpha leads into complete recommendation tickets or watchlist-only rows.

**Files likely touched:**
- Create: `/root/.hermes/wolfy/lead_promotion_gate.py`
- Test: `/root/.hermes/wolfy/test_lead_promotion_gate.py`
- Reuse: `/root/.hermes/wolfy/recommendation_logger.py`
- Reuse: `/root/.hermes/wolfy/suspicious_activity.py`

**Acceptance criteria:**
1. Reads latest scanner results and alpha leads/evidence.
2. Requires fresh scanner data, non-price thesis, technical setup, entry, stop, target, R/R, sizing, risk notes, RH assumption, and Jonah references.
3. Vetoes/flags foreign, manipulation, pump-and-dump, low-liquidity, no-catalyst, and PDT/account risks.
4. Complete ideas become `pending_review` through `recommendation_logger.py`.
5. Incomplete ideas become `watching`/watch-only with validation notes.
6. Test fixtures cover promoted, watch-only, stale-data, and risk-veto cases.

**Verification commands:**
```bash
python -m pytest -q /root/.hermes/wolfy/test_lead_promotion_gate.py /root/.hermes/wolfy/test_recommendation_logger.py
python /root/.hermes/wolfy/lead_promotion_gate.py --db /root/.hermes/wolfy/wolfy.db --dry-run
```

## Task P3: Report-Flow Integration

**Objective:** Make the twice-daily Wolfy report consume promotion-gate state without manual prompting.

**Files likely touched:**
- Modify: `/root/.hermes/wolfy/wolfy_report_context.py`
- Possibly modify: `/root/.hermes/scripts/wolfy_report_context.py`
- Possibly create: report-context fixture test/smoke helper.

**Acceptance criteria:**
1. Report context includes scanner freshness, promoted pending_review recommendations, watch-only reasons, and Sentinel/paper status.
2. Report distinguishes scanner leads from actual pending_review trade tickets.
3. If no complete ticket exists, Wolfy reports no-trade/watchlist with reason.
4. Cron job `ba183091b5c0` does not require manual intervention.

**Verification commands:**
```bash
python /root/.hermes/wolfy/wolfy_report_context.py
hermes --profile default cron list --all
```

## Task P4: Sentinel Review Persistence

**Objective:** Persist Sentinel's decisions and update recommendation status.

**Kanban card:** `t_b51dea08`

**Acceptance criteria:**
1. Reads `pending_review` recommendations.
2. Runs deterministic checks for required fields, account constraints, risk/reward, stops, concentration, PDT, RH assumption, and manipulation/foreign risk.
3. Writes structured review rows to Postgres `recommendation_reviews` or durable equivalent.
4. Updates SQLite recommendation status to `approved`, `rejected`, or `needs_revision`.
5. Includes fixture/smoke test.

## Task P5: Paper Portfolio Engine and Outcome Grader

**Objective:** Track approved paper candidates through entry, stop, target, PnL, and R-multiple.

**Kanban card:** `t_34c824e2`

**Acceptance criteria:**
1. Creates paper candidates only from approved/reviewed recommendations.
2. Enforces max 3 concurrent positions and $5,000 paper account risk limits.
3. Tracks trigger, open, close, stop, target, PnL, R multiple, days held, max adverse/favorable excursion.
4. Writes to `paper_trades` and `recommendation_outcomes`.
5. Uses delayed/free data only and does not claim live execution.
6. Includes dry-run/smoke test.

## Task P6: End-to-End Smoke and Cron Handoff

**Objective:** Prove the full accountability loop works and will keep running autonomously.

**Kanban card:** `t_3e5cd5eb`

**Acceptance criteria:**
1. Run end-to-end dry-run through scanner -> promotion -> pending_review -> Sentinel -> paper ledger -> outcome grader.
2. Use fixtures/temp DB or explicitly tagged no-op rows that are cleaned up.
3. Verify existing cron jobs consume new scripts.
4. Add or adjust scheduled no-agent helpers only if needed.
5. Final handoff lists commands run, rows created/updated, and next autonomous cron behavior.

## Autonomy Rules

- Clerky/Mike/Wolfy should keep moving through these cards via the existing Kanban allocator and dispatcher.
- Do not ask the user before routine code/test/schema-compatible changes.
- Ask the user only for destructive DB/package changes, paid API credentials, broker/live-trading authority, or unresolved legal/data-access blockers.
- Do not place real trades.
- Do not claim a card complete without real command output.
