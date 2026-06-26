# Wolfy Daily Optimization TODO Ledger

Durable trail for the daily Wolfy/Hermes optimization planner. Items here are planning/implementation notes only; they do not authorize trading, broker access, money movement, or strategy approval.

## Operating constraints

- EOD-only: actionable decisions use closing data and deterministic signal/risk gates.
- Human approval required before any strategy becomes approved/actionable.
- Robinhood-tradable U.S. stocks/ETFs only; long-only equities/ETFs; options allowed only as defined-risk paper-trading structures.
- Max 3 concurrent positions, stops/invalidation required, no shorts, no auto-execution.
- Avoid foreign/government-interference/manipulation-risk names.
- Postgres is live source of truth; run `/root/.hermes/wolfy/check_postgres_requirements.py` before Postgres package/schema maintenance.

## 2026-06-19 daily run

Snapshot/conflict check:

- Time: 2026-06-19 02:15 ET.
- Git status: working tree already had many pre-existing Wolfy/Hermes edits and untracked files; this run must stay bounded and avoid broad refactors.
- Cron/processes: gateway running; no active Wolfy worker process at snapshot time. Near-term no-agent jobs due around 02:28-02:30 ET: stale coordination watchdog, safe autorepair, storage watchdog, usage-limit watchdog, embedding sync. Market/report windows are later (08:00 pre-open, 10:00 intraday scanner, 16:30/17:05/17:35+ EOD). Safe to add standalone read-only/reporting helper and this ledger; avoid editing scripts those 02:28-02:30 jobs invoke.
- Recent cron failures: Jonah LLM knowledge builder paused after HTTP 429 usage limit; several LLM report/reviewer jobs are paused. Script-only EOD/data/watchdog jobs are active and recently OK.

### Candidate: visible-progress-ledger

- Status: implemented-bounded 2026-06-19.
- Owner/job: Wolfy daily optimization planner; future candidate for Clerky/activity or pre-open context if user wants scheduled delivery.
- Files/tables/jobs affected: add `/root/.hermes/wolfy/visible_progress_ledger.py`; read-only access to Postgres tables `prices`, `features`, `signals`, `setups`, `strategies`, `scanner_runs`, `scanner_results`, `agent_runs`, `agent_tasks`, `paper_trades`, `recommendations`, `recommendation_reviews`; no cron changes.
- Expected benefit: gives a deterministic concise Markdown status covering data freshness, signal/setup gates, validation strategy status, blockers, and next action so the user can see concrete progress without an LLM re-querying schemas or inventing activity.
- Risk: low. Read-only script; no DB writes, no trading action, no schedule mutation.
- Rollback: delete `/root/.hermes/wolfy/visible_progress_ledger.py` and remove this entry.
- Tests/validation: Python compile check and `python3 visible_progress_ledger.py --json` / Markdown dry run.
- Conflict result: no direct file conflict; implementation avoids near-term active scripts and runs before market/report windows.

### Candidate: trend-volume-strategy

- Status: deferred.
- Owner/job: Wolfy EOD weekly research/backtest lane.
- Impact plan: improve `trend_volume_vol_regime` definition and walk-forward OOS validation. Likely affects strategy params, features/signals, backtest scripts/tables, and weekly research context.
- Expected benefit: moves one core strategy toward candidate-quality validation while preserving human approval gate.
- Risk: medium/high for this run because broad backtest/schema work could exceed two-file throttle and long-running data jobs could overlap scheduled no-agent jobs.
- Rollback: revert touched strategy/backtest files and discard generated validation rows/artifacts.
- Tests/validation: targeted unit tests plus read-only strategy/signal counts and OOS report artifact.
- Conflict result: deferred due broad scope, many pre-existing worktree edits, and upcoming script-only cron jobs.

### Candidate: paper-postgres

- Status: deferred.
- Owner/job: Wolfy accountability/paper ledger migration lane.
- Impact plan: migrate remaining paper portfolio/trade ledger consumers away from SQLite to Postgres; likely touches weekly scorecard, paper ledger tables, tests, and cron/report contexts.
- Expected benefit: removes live SQLite dependence and improves accountability/report quality.
- Risk: medium/high for this run because it needs schema/consumer inventory and likely exceeds two-file throttle; Postgres maintenance/schema changes require explicit guard checks.
- Rollback: revert consumer changes; keep SQLite archive until explicit deletion approval.
- Tests/validation: run `check_postgres_requirements.py` before schema work, targeted ledger tests, Postgres row-count smoke, exact context-script smoke.
- Conflict result: deferred; record for future bounded migration slice.

### Candidate: backlog-hygiene

- Status: deferred.
- Owner/job: Clerky/Kanban allocator lane.
- Impact plan: dedupe Jonah/Sentinel/Yang backlog and prioritize current high-value tasks.
- Expected benefit: reduces repeated research/noise and focuses agents on validation/accountability.
- Risk: medium because it may mutate Kanban/task state and could conflict with active allocator/stale cleanup jobs.
- Rollback: Kanban comments/unblock changes are auditable but not trivial to undo cleanly.
- Tests/validation: board list before/after, exact non-destructive verification for review-only blockers.
- Conflict result: deferred because allocator/stale-cleanup no-agent jobs are active and due soon.

## 2026-06-20 daily run

Snapshot/conflict check:

- Time: 2026-06-20 02:15 ET.
- Git status: working tree already had many pre-existing Wolfy/Hermes edits and untracked scratch/research files; this run stays bounded and does not commit.
- Cron/processes: gateway and Postgres are running. No separate active Wolfy ingestion/report worker process was present in the process snapshot. Near-term scheduled jobs include Jonah knowledge builder at 02:20, storage/usage/embedding jobs at 02:30, stale coordination cleanup at 02:36, and safe autorepair at 02:40. Market/report windows are not active on Saturday; next EOD/report windows are Monday.
- Recent cron failures/logs: current cron log file was absent/empty in the checked path; gateway error tail showed stale 2026-05-31 Kanban/Discord errors only, not a current Wolfy blocker.

### Candidate: visible-progress-ledger-historical-depth-gate

- Status: implemented-bounded 2026-06-20.
- Owner/job: Wolfy daily optimization planner; useful for future Clerky/activity/pre-open context.
- Files/tables/jobs affected: modified `/root/.hermes/wolfy/visible_progress_ledger.py`; read-only queries against Postgres `prices` and `features`; no cron/job changes; no DB writes.
- Expected benefit: adds a deterministic historical-depth gate to the visible progress ledger so strategy/backtest readiness can be judged from actual price-bar coverage before trusting walk-forward OOS results.
- Risk: low. Script remains read-only and does not approve strategies, create setups, or move money.
- Rollback: revert the `visible_progress_ledger.py` changes from this run.
- Tests/validation: Python compile check, JSON dry run, Markdown dry run.
- 2026-06-20 07:17 ET ops follow-up: restored executable bit and added CLI compatibility aliases `--format markdown|json` and `--limit N` after smoke checks found the helper itself was healthy but tolerant argument parsing was missing. Verified compile, Markdown dry run, JSON dry run, and two silent safe-autorepair sync runs; no DB writes.
- Conflict result: safe to implement because it is a lightweight read-only helper change and does not touch files invoked by the imminent 02:20/02:30 jobs.

### Candidate: trend-volume-strategy

- Status: deferred-next-slice.
- Owner/job: Wolfy EOD weekly research/backtest lane.
- Impact plan: improve `trend_volume_vol_regime` definition, then run a bounded walk-forward OOS dry run on liquid U.S. tickers after confirming historical depth is adequate.
- Expected benefit: advances a core strategy toward candidate-quality validation while preserving candidate-not-approved and human approval gates.
- Risk: medium for this run because code/backtest changes plus DB-written backtests could exceed the two-file/time throttle and overlap frequent cron jobs.
- Rollback: revert strategy/backtest code changes and discard any generated validation rows/artifacts.
- Tests/validation: targeted `test_eod_signals.py` / `test_eod_backtest.py`, read-only depth check, then a dry-run or explicitly bounded OOS artifact.
- Conflict result: deferred; today’s safe implementation adds the depth visibility needed before trusting broader OOS work.

### Candidate: paper-postgres

- Status: deferred.
- Owner/job: Wolfy accountability/paper ledger migration lane.
- Impact plan: inventory remaining SQLite paper-ledger live consumers and migrate one bounded consumer at a time to Postgres-only operation.
- Expected benefit: removes live SQLite dependence from paper portfolio/accountability reports.
- Risk: medium/high because it may touch schema/consumer behavior; Postgres schema work requires `/root/.hermes/wolfy/check_postgres_requirements.py` first.
- Rollback: revert consumer changes; leave SQLite as legacy archive until explicit deletion approval.
- Tests/validation: Postgres guard, targeted ledger tests, representative context smoke.
- Conflict result: deferred due scope and active frequent operations jobs.

### Candidate: backlog-hygiene

- Status: deferred.
- Owner/job: Clerky/Kanban allocator lane.
- Impact plan: dedupe stale Jonah/Sentinel/Yang backlog and prioritize current strategy validation/accountability tasks.
- Expected benefit: reduces repeated research/noise and focuses workers on validation and paper-ledger migration.
- Risk: medium because it mutates task/board state and can collide with allocator/stale cleanup jobs.
- Rollback: comments/status changes are auditable but not trivially reversible.
- Tests/validation: board list before/after and exact verification for any review-only blockers.
- Conflict result: deferred; allocator/stale-cleanup jobs remain active.

## 2026-06-21 daily run

Snapshot/conflict check:

- Time: 2026-06-21 02:15 ET / 06:15 UTC.
- Git status: working tree already had many pre-existing Wolfy/Hermes edits and untracked research/scratch files; this run stays bounded and does not commit.
- Cron/processes: gateway running; no separate active Wolfy worker process at snapshot time. Near-term scheduled jobs include Jonah at 02:20, stale coordination cleanup and safe autorepair around 02:24, and storage/usage/embedding jobs at 02:30. Market/report windows are not active on Sunday; next market/report windows are Monday.
- Recent cron output: recent agent log shows Mike repair loop and no-agent watchdogs completing successfully/silently; Jonah 02:00 returned `[SILENT]`; no current Wolfy failure was found in the tailed logs.

### Candidate: visible-progress-ledger-backlog-hygiene-snapshot

- Status: implemented-bounded 2026-06-21.
- Owner/job: Wolfy daily optimization planner; useful for Clerky/activity ledger and future backlog-hygiene planning.
- Files/tables/jobs affected: modified `/root/.hermes/wolfy/visible_progress_ledger.py`; read-only query against Postgres `agent_tasks`; no DB writes, cron/job changes, strategy approvals, setup creation, or trading actions.
- Expected benefit: surfaces queued/ready, in-progress, blocked, stale-in-progress, and duplicate-active-fingerprint counts in the deterministic visible ledger so backlog hygiene can be planned from facts before mutating any task state.
- Risk: low. Strictly read-only helper output; it does not pause/remove/update jobs or mutate Kanban/Postgres rows.
- Rollback: revert the `visible_progress_ledger.py` changes from this run.
- Tests/validation: Python compile check, JSON dry run, Markdown dry run with `--limit 2`, and direct Postgres count query for `agent_tasks` status distribution.
- Conflict result: safe because it is a lightweight read-only helper change completed before market/report windows and does not edit scripts invoked by the imminent no-agent jobs.

### Candidate: trend-volume-strategy

- Status: deferred-next-slice.
- Owner/job: Wolfy EOD weekly research/backtest lane.
- Impact plan: improve `trend_volume_vol_regime` definition and run a bounded walk-forward OOS dry run only after historical-depth and feature freshness gates pass.
- Expected benefit: advances the core EOD strategy toward candidate-quality validation while keeping `candidate is not approved` visible and requiring human approval for actionability.
- Risk: medium for this run because strategy/backtest edits and OOS artifacts could exceed the two-file throttle and overlap frequent operations jobs.
- Rollback: revert strategy/backtest code changes and discard generated validation artifacts/rows.
- Tests/validation: targeted strategy unit tests, read-only depth/freshness gate, then bounded OOS artifact.
- Conflict result: deferred; today’s bounded change improves visibility for backlog hygiene without running long data/backtest work near scheduled jobs.

### Candidate: paper-postgres

- Status: deferred.
- Owner/job: Wolfy accountability/paper ledger migration lane.
- Impact plan: inventory and migrate one remaining live paper-ledger SQLite consumer to Postgres-only behavior, guarded by `/root/.hermes/wolfy/check_postgres_requirements.py` if schema work is needed.
- Expected benefit: removes live SQLite dependence from paper portfolio/accountability reports.
- Risk: medium/high for this run because it may touch schema or multiple consumers.
- Rollback: revert consumer/schema changes; keep SQLite as legacy archive until explicit deletion approval.
- Tests/validation: Postgres guard, targeted ledger tests, representative context smoke.
- Conflict result: deferred due scope and frequent active operations jobs.

### Candidate: visible-progress-ledger

- Status: maintained.
- Owner/job: Wolfy daily optimization planner.
- Impact plan: continue using the deterministic ledger for data freshness, signals, setups, strategy gates, blockers, historical depth, and now backlog-hygiene facts.
- Expected benefit: keeps daily visible progress concrete and low-token.
- Risk: low as long as it remains read-only.
- Rollback: revert helper changes.
- Tests/validation: compile and smoke output.
- Conflict result: no conflict from read-only smoke tests.

## 2026-06-22 daily run

Snapshot/conflict check:

- Time: 2026-06-22 02:16 ET / 06:16 UTC.
- Git status: working tree already had many pre-existing Wolfy/Hermes edits and untracked research/scratch files; this run stays bounded and does not commit.
- Cron/processes: gateway and Postgres are running. Default-profile cron has frequent jobs due soon: Jonah at 02:20, Mike environment repair around 02:29, storage/usage/embedding/allocator/stale-cleanup/safe-autorepair around 02:30, plus market/report windows later (08:00 pre-open/monthly revalidation, 10:00 scanner, 16:30+ EOD). No separate active Wolfy/Jonah/Sentinel/Yang worker process was present in the snapshot. `/root/.hermes/cron/.tick.lock` existed with current mtime, consistent with scheduler activity/current cron context; no cron files were modified.
- Recent cron output: default cron list reports recent OK runs; checked gateway/error/cron log paths showed no recent failure keywords in the last gateway tail and missing cron/error log files at checked paths.

### Candidate: visible-progress-ledger-strategy-readiness

- Status: implemented-bounded 2026-06-22.
- Owner/job: Wolfy daily optimization planner; useful for future Clerky/activity/pre-open context.
- Files/tables/jobs affected: modified `/root/.hermes/wolfy/visible_progress_ledger.py`; read-only joins across Postgres `strategies`, `signals`, and `setups`; no DB writes, cron/job changes, strategy approvals, setup creation, or trading actions.
- Expected benefit: surfaces deterministic per-strategy signal/setup readiness directly in the visible ledger, making `trend_volume_vol_regime` progress and the approved-strategy gate easier to audit before walk-forward/OOS work.
- Risk: low. Strictly read-only helper output and one-file change; does not touch scripts invoked by imminent 02:20/02:30 jobs.
- Rollback: revert the `visible_progress_ledger.py` changes from this run.
- Tests/validation: Python compile check, JSON dry run, Markdown dry run with `--limit 2`, and direct read-only Postgres schema/column inspection.
- Conflict result: safe to implement because it is lightweight and read-only; no market/report window active. Avoided backlog/task mutation, Postgres schema maintenance, long backtests, and cron edits due the active/frequent operations schedule.

### Candidate: trend-volume-strategy

- Status: deferred-next-slice.
- Owner/job: Wolfy EOD weekly research/backtest lane.
- Impact plan: improve `trend_volume_vol_regime` definition and run bounded walk-forward OOS only after historical-depth, feature freshness, and deterministic readiness gates pass.
- Expected benefit: advances the core EOD strategy toward candidate-quality validation while keeping candidate/research outputs non-actionable until human approval.
- Risk: medium for this run because strategy/backtest edits and generated artifacts could exceed the two-file throttle and overlap frequent operations jobs.
- Rollback: revert strategy/backtest code changes and discard generated validation artifacts/rows.
- Tests/validation: targeted strategy tests, read-only depth/freshness/readiness gate, then a bounded dry-run/OOS artifact.
- Conflict result: deferred; today’s bounded implementation improves visibility needed before safe strategy work.

### Candidate: paper-postgres

- Status: deferred.
- Owner/job: Wolfy accountability/paper ledger migration lane.
- Impact plan: inventory and migrate one remaining live paper-ledger SQLite consumer to Postgres-only behavior, guarded by `/root/.hermes/wolfy/check_postgres_requirements.py` if schema work is needed.
- Expected benefit: removes live SQLite dependence from paper portfolio/accountability reports.
- Risk: medium/high for this run because it may touch schema or multiple consumers.
- Rollback: revert consumer/schema changes; keep SQLite as legacy archive until explicit deletion approval.
- Tests/validation: Postgres guard, targeted ledger tests, representative context smoke.
- Conflict result: deferred due scope and frequent active operations jobs.

## 2026-06-25 daily run

Snapshot/conflict check:

- Time: 2026-06-25 02:15 ET / 06:15 UTC.
- Git status: working tree already had many pre-existing Wolfy/Hermes edits and untracked research/scratch files; this run stays bounded and does not commit.
- Cron/processes: gateway and Postgres are running; no separate active Wolfy/Jonah/Sentinel/Yang worker process was present in the process snapshot. Frequent jobs were due soon: Jonah at 02:20, storage/usage/embedding at 02:30, stale cleanup and safe autorepair at ~02:37, allocator at 03:00, Clerky at 04:00. Market/report windows are later (08:00 pre-open, 10:00 intraday, 16:30+ EOD), so only lightweight read-only helper work is safe.
- Recent cron output: default cron shows most jobs OK/silent; previous daily optimizer run failed with HTTP 429 usage limit, while the 02:00 usage watchdog was silent. Recent agent log contains Jonah ad-hoc query/tool warnings inside an otherwise successful run, not a reason to mutate schema from this optimizer.

### Candidate: visible-progress-ledger-paper-accountability-gate

- Status: implemented-bounded 2026-06-25.
- Owner/job: Wolfy daily optimization planner; useful for Clerky/activity/pre-open context and for the `paper-postgres` migration trail.
- Files/tables/jobs affected: modified `/root/.hermes/wolfy/visible_progress_ledger.py`; read-only queries against Postgres `paper_trades` and `recommendations`; no DB writes, cron/job changes, strategy approvals, setup creation, or trading actions.
- Expected benefit: surfaces paper-ledger/recommendation accountability facts in the deterministic visible ledger: total/open paper trades, open trades missing stops, closed PnL total, latest paper trade date, pending recommendations, and pending recommendations missing stops. This makes the Postgres paper-ledger gap visible before any migration mutation.
- Risk: low. Strictly read-only helper output and one-file change; no Postgres schema maintenance, no long data jobs, and no edits to scripts invoked by the imminent no-agent jobs.
- Rollback: revert the `visible_progress_ledger.py` changes from this run.
- Tests/validation: Python compile check, JSON dry run, Markdown dry run with `--limit 2`, and direct read-only Postgres schema/status-count inspection.
- Conflict result: safe to implement because it is lightweight and read-only; avoided backlog/task mutation, strategy/backtest changes, cron edits, and DB maintenance during frequent operations windows.

### Candidate: trend-volume-strategy

- Status: deferred-next-slice.
- Owner/job: Wolfy EOD weekly research/backtest lane.
- Impact plan: improve `trend_volume_vol_regime` definition and run bounded walk-forward OOS only after historical-depth, feature freshness, strategy-readiness, and paper/accountability gates are visible.
- Expected benefit: advances the core EOD strategy toward candidate-quality validation while keeping candidate/research outputs non-actionable until human approval.
- Risk: medium for this run because strategy/backtest edits and generated artifacts could exceed the two-file throttle and overlap frequent operations jobs.
- Rollback: revert strategy/backtest code changes and discard generated validation artifacts/rows.
- Tests/validation: targeted strategy tests, read-only depth/freshness/readiness gate, then a bounded dry-run/OOS artifact.
- Conflict result: deferred; today’s bounded implementation improves accountability visibility needed before safe strategy work.

### Candidate: paper-postgres

- Status: advanced-read-only; migration deferred.
- Owner/job: Wolfy accountability/paper ledger migration lane.
- Impact plan: finish inventory and migrate one remaining live paper-ledger SQLite consumer to Postgres-only behavior, guarded by `/root/.hermes/wolfy/check_postgres_requirements.py` if schema work is needed.
- Expected benefit: removes live SQLite dependence from paper portfolio/accountability reports.
- Risk: medium/high for this run because true migration may touch schema or multiple consumers; current run intentionally only adds read-only Postgres visibility.
- Rollback: revert consumer/schema changes if future migration is attempted; keep SQLite as legacy archive until explicit deletion approval.
- Tests/validation: Postgres guard before schema work, targeted ledger tests, representative context smoke, and visible ledger paper/accountability section.
- Conflict result: deferred for mutation; read-only visibility was safe.
