# Wolfy visible progress ledger: deterministic strategy readiness (2026-06-22)

Context: Daily Wolfy optimization planner needed a safe bounded improvement while frequent cron jobs were active. Broader strategy/backtest work and paper-ledger migration were deferred to avoid collisions.

## Safe optimization pattern

Add visibility first when implementation/backtest work is too broad for the daily optimizer window. Extend the read-only visible progress ledger rather than mutating strategy/task/paper-ledger state.

Implemented shape in `/root/.hermes/wolfy/visible_progress_ledger.py`:

- Add a read-only `strategy_readiness` section joining Postgres `strategies`, `signals`, and `setups`.
- Report per strategy:
  - `status`
  - latest deterministic signal date
  - signal count at the latest signal date
  - total signal count
  - latest setup date
  - open/pending setup count
  - gate note
- Gate wording:
  - `approved` -> approved-strategy gate can be evaluated against deterministic risk checks.
  - no deterministic signals -> research/watch-only.
  - non-approved with signals -> candidate/research only; candidate is not approved.

Representative verification output from the run:

```text
json ok
strategy_readiness_rows 3
pead research_only None 0 0 no deterministic signals yet; research/watch-only
sector_cross_sectional_momentum candidate 2026-06-18 10 0 candidate/research only; candidate is not approved
trend_volume_vol_regime research_only 2026-06-18 6 0 candidate/research only; candidate is not approved
```

Markdown smoke should include a `## Deterministic strategy readiness` table and explicitly keep `trend_volume_vol_regime` watch-only until human approval.

## Conflict discipline

Before editing, snapshot:

1. Current local and UTC time.
2. `git status` for `/root/.hermes`.
3. `hermes --profile default cron list --all`.
4. Relevant running processes.
5. Recent failure/log tails.
6. Lock files such as `/root/.hermes/cron/.tick.lock`.

If frequent jobs are imminent or a scheduler lock is fresh, avoid cron/job edits, task-state mutations, long market-data jobs, and DB schema changes. A one-file read-only helper patch plus the durable optimization TODO ledger is usually safe if no active worker process owns that file.

## Deferred next slices

- `trend-volume-strategy`: improve `trend_volume_vol_regime` and run bounded walk-forward/OOS only after historical-depth, feature freshness, and strategy-readiness gates pass.
- `paper-postgres`: inventory and migrate one remaining live paper-ledger SQLite consumer at a time; run the Postgres guard before schema work.
- Backlog hygiene mutations: defer when allocator/stale-cleanup jobs are active or due soon; use read-only snapshots instead.
