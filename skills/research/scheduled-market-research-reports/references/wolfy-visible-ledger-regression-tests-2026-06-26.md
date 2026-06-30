# Wolfy visible ledger regression tests (2026-06-26)

Session pattern for the daily Wolfy optimization planner: when the visible progress ledger has accumulated several safety-critical sections, a high-value bounded optimization can be to add/maintain local regression tests rather than adding another output section.

## Trigger

Use this when `/root/.hermes/wolfy/visible_progress_ledger.py` is already the low-token, deterministic status surface and future edits risk dropping or weakening:

- EOD-only / closing-data-only constitution language.
- No auto-execution / no live trading language.
- Human approval requirement.
- `candidate is not approved` gate wording.
- Paper/accountability-only wording.
- Core Markdown sections used by Clerky/activity/pre-open contexts.

## Safe implementation shape

Add or update `/root/.hermes/wolfy/test_visible_progress_ledger.py` with pure render-level tests that import `render_markdown()` and pass a synthetic `collect_progress()`-shaped dict. Do **not** connect to Postgres or mutate task/strategy state in these tests.

Assertions that proved useful:

- Output contains `closing-data only`, `no auto-execution`, and `human approval required`.
- Candidate/non-approved strategies render `candidate is not approved`.
- Paper ledger section renders `paper/accountability only; no live trading or auto-execution`.
- Core headings remain present:
  - `## Snapshot`
  - `## Strategy gates`
  - `## Latest walk-forward validation`
  - `## Deterministic strategy readiness`
  - `## Paper/accountability gate`
  - `## Blockers / noise`
  - `## Next recommended action`

## Verification commands

From `/root/.hermes/wolfy`:

```bash
python3 -m py_compile visible_progress_ledger.py test_visible_progress_ledger.py
python3 -m pytest test_visible_progress_ledger.py -q
python3 visible_progress_ledger.py --format json --limit 0 >/tmp/wolfy_visible_progress_ledger.json
python3 visible_progress_ledger.py --limit 0
```

Expected target: compile succeeds, the targeted pytest file passes quickly, JSON parses, and Markdown smoke still prints current data freshness / strategy gates without creating setups, approving strategies, or writing database rows.

## Why this matters

For Wolfy, visibility is part of the safety system. A deterministic ledger that accidentally drops the non-actionability or approval-gate wording can make research-only/candidate signals look more actionable than they are. Render-level tests are cheap, run under the daily optimizer throttle, and avoid conflicts with frequent ingestion/report/watchdog cron jobs.
