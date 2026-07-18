# Wolfy Daily Optimization TODO Ledger

Durable trail for the daily Wolfy/Hermes optimization planner. Items here are planning/implementation notes only; they do not authorize trading, broker access, money movement, or strategy approval.

## Operating constraints

- EOD-only: actionable decisions use closing data and deterministic signal/risk gates.
- Human approval required before any strategy becomes approved/actionable.
- Robinhood-tradable U.S. stocks/ETFs only; long-only equities/ETFs; options allowed only as defined-risk paper-trading structures.
- Max 3 concurrent positions, stops/invalidation required, no shorts, no auto-execution.
- Avoid foreign/government-interference/manipulation-risk names.
- Postgres is live source of truth; run `/root/.hermes/wolfy/check_postgres_requirements.py` before Postgres package/schema maintenance.
- Daily optimization runs should send a short completion report when done: what changed, verification, commit/KPI, blockers/next action only.

## 2026-07-18 daily optimizer plan-only run

- Time: 2026-07-18 02:15 ET / 06:15 UTC.
- Budget gate: `python3 wolfy/guardian/budget_gate.py` returned `BUDGET=block token_cap_exceeded tokens_today=332044 cap=200000` (exit 1), so this run followed the PLAN-ONLY rule: review/state/KPI updates only, no code/config/cron implementation.
- Guardian/probation: no probation marker existed; `python3 wolfy/guardian/config_guardian.py` returned `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;hermes_cron_list_ok;no_probation` (exit 0), and `hermes cron list` succeeded with optimizer `92f31b95fccc` still active.
- State: created/claimed/completed Postgres task `3575` and run `322840`; recorded KPI rows for tokens/headroom, budget skip, guardian/gateway health, data freshness/depth, migration posture, loop health, strategy counts, and repo size.
- NEXT ACTION: when budget headroom recovers, execute exactly one Tier S control-plane slice. Preferred queued task remains `3546` / OWS-4: reduce Jonah cadence from `*/20` to hourly under the self-modification protocol; otherwise finish remaining OWS-1 no-op coverage if budget-gate gaps are found.

## 2026-07-17 daily optimizer plan-only run

- Time: 2026-07-17 02:16 ET / 06:16 UTC.
- Budget gate: `python3 wolfy/guardian/budget_gate.py --no-record` returned `BUDGET=block token_cap_exceeded tokens_today=270998 cap=200000` (exit 1), so this run followed the PLAN-ONLY rule: review/state/KPI updates only, no code/config/cron implementation.
- Guardian/probation: no probation marker existed; `python3 wolfy/guardian/config_guardian.py` returned `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;hermes_cron_list_ok;no_probation` (exit 0), and `hermes cron list` succeeded with optimizer `92f31b95fccc` still active.
- State: created/claimed/completed Postgres task `3569` and run `319202`; recorded KPI rows for tokens/headroom, budget skip, guardian/gateway health, data freshness/depth, migration posture, loop health, strategy counts, and repo size.
- NEXT ACTION: when budget headroom recovers, execute exactly one Tier S control-plane slice. Preferred queued task remains `3546` / OWS-4: reduce Jonah cadence from `*/20` to hourly under the self-modification protocol; otherwise finish remaining OWS-1 no-op coverage if budget-gate gaps are found.

## Explicit user-directed data-load control TODO — 2026-07-02

### ONE-TIME Massive 2-year history bootstrap; daily ingest must stay incremental-only

- Status: queued in Postgres `agent_tasks` as task `3281` with fingerprint `one-time-massive-history-bootstrap-incremental-daily-20260702`.
- Requirement: the initial two-calendar-year Massive OHLCV history load is a bootstrap/backfill task only. Normal daily EOD pipelines must not re-pull two years every day.
- Current code guard to preserve: `/root/.hermes/wolfy/eod_price_features.py` uses `_fetch_incremental_massive_bars()`: full `days=730` is only used when a ticker is missing/under `min_history_bars`; otherwise the fetch starts at `latest_dt + 1` or skips as `already_current`.
- Required cleanup: make the bounded tiered history backfill job visibly one-time/run-until-complete and auto-disable/no-op once active targets reach `DEPTH_READY_BARS`/`min_history_bars=495`; keep daily shards focused on current/missing-day ingest.
- DoD: coverage query shows completed/remaining bootstrap universe; backfill job completion behavior is verified; daily shard test/dry-run proves already-loaded tickers do not fetch full 730-day history; visible ledger separates `bootstrap_remaining` from daily freshness.

## Data & Learning Backlog (DQ/VAL/LRN) — user-approved 2026-07-01

Standing backlog for the daily optimizer: consume these as Phase 2 planning candidates alongside the
embedded WS/OWS items, in the sequencing given at the bottom. Tier S = implement in bounded slices with
a machine-checkable Definition of Done; Tier B = recommend and wait. Direction ratchet applies: numeric
gates below may only tighten without human review.

## P0 — SILENT CORRECTNESS BUGS (fix before trusting any signal or backtest)

### DQ-1 — Split-safe ingest: re-fetch full history on corporate actions  [Tier S]
Problem: incremental ingest fetches only latest_dt+1 forward. After a split, the provider re-adjusts ALL
history, but Wolfy keeps stale pre-split-adjusted bars and appends new ones — the prices table mixes
adjustment bases; features/signals/backtests on that ticker are silently wrong. The validator only tags
recent_split_requires_adjustment_audit (severity review); nothing acts on it, and the 45-day lookback
never audits older splits.
Fix (slices): (a) when corporate actions show a split for a ticker since its earliest stored bar, force
a FULL re-fetch (start_dt = full_start_dt) and upsert-replace its history; (b) escalate unresolved split
audits from review to blocker after one ingest cycle; (c) one-time repair: scan splits over the full
stored window for all tracked tickers and queue full re-fetches for any affected.
DoD: unit test simulating a split yields a fetch plan with reason=corporate_action_refetch and
start_dt=full_start_dt; after re-ingest, price_data_quality_events has no unresolved split audits;
second run idempotent (0 new rows); suite 0 regressions.

### DQ-2 — Populate `earnings_calendar` (read by 4 modules, written by none)  [Tier S]
Problem: PEAD signals, event-landmine checks, monitoring, and the promotion gate all query
earnings_calendar, but no ingest populates it. PEAD emits nothing and the "don't hold through earnings"
safety check silently passes on an empty table.
Fix: deterministic wolfy/earnings_calendar_ingest.py + no_agent cron wrapper pulling upcoming/recent
earnings dates for tracked tickers from the primary provider's reference endpoints if available on the
current plan. If the plan lacks an earnings endpoint, file a Tier B recommendation naming the exact
source/key needed and meanwhile make the landmine check FAIL-CLOSED: a ticker with no earnings coverage
returns state earnings_unknown on the ticket instead of implying safety.
DoD: count of future earnings rows covers ≥90% of tier-1/2 tickers (or the Tier B rec is filed and
fail-closed behavior is tested); PEAD on a fixture produces ≥1 signal; landmine check on an uncovered
ticker returns earnings_unknown; ledger gains earnings_coverage_pct.

### DQ-3 — Bar-level sanity gates on ingest  [Tier S]
Problem: only missing-history and >5-day staleness are validated. No OHLC integrity, outlier, duplicate,
or zero checks; None bars are skipped silently and uncounted.
Fix: extend validation (or a pre-store gate) to record events for: high<low; high<max(open,close);
low>min(open,close); price ≤ 0; volume < 0; duplicate (ticker,dt); |1-day close move| > 40% with NO
corporate action (severity review); zero-volume streaks ≥3 days on tier-1/2. Count and report
skipped-None bars per run. Tighten max_stale_days for tier-1/2 to 2 (blocker), keep 5 for lower tiers.
DoD: fixture with each malformed-bar class produces exactly the expected quality events; clean fixture
produces 0; skipped-None count in ingest summary; ledger freshness gate reflects the tighter threshold.

## P1 — VALIDATION STATISTICS (stop weak strategies from reaching candidate)

### VAL-1 — Minimum OOS evidence before `survives_oos`  [Tier S]
Problem: survives_oos passes on OOS Sharpe alone — a single OOS trade can promote to candidate; no
trade-count floor exists.
Fix: add min_oos_trades (default 20) and min_is_trades (default 60) as governed config with the same
"may only increase without human review" ratchet used for costs. Record oos_trades/is_trades in the
verdict reason on failure.
DoD: fixture with 5 OOS trades and high Sharpe → survives_oos=false, reason insufficient_oos_trades;
fixture with ≥20 passes; ratchet tested; suite green.

### VAL-2 — Rolling walk-forward instead of single terminal holdout  [Tier S, sliced]
Problem: OOS = last 63 exit dates once; one favorable terminal regime can pass a fragile strategy.
Fix: k anchored expanding-window folds (e.g. 4×63d). survives_oos requires pooled OOS Sharpe ≥ threshold
AND ≥3/4 folds individually non-negative. Persist per-fold results in the backtest report JSON.
DoD: fixture where only fold 4 is strong → fails; uniform-edge fixture passes; per-fold array present;
existing single-holdout callers migrated.

### VAL-3 — Multiple-testing discipline  [Tier S]
Problem: nothing tracks how many strategy/param variants were tried; some will pass OOS by luck.
Fix: strategy_trials counter table incremented per backtest per family; trials-per-family in the ledger;
deterministic deflation rule (e.g. min_oos_sharpe + 0.1×log2(trials)), configurable and ratcheted.
DoD: families with 1 vs 32 trials face measurably different thresholds in a test; counter increments
exactly once per run (idempotent re-run doesn't double).

### VAL-4 — Survivorship-bias containment  [Tier S now, Tier B for point-in-time data]
Problem: universe seeds from CURRENT index membership; backtests only see survivors; results inflated.
Fix now: stamp every backtest report with universe_asof + survivorship_bias=true; never delete a
removed ticker's price history; ledger discloses the caveat so Sentinel/Yang see it on every candidate.
Fix later (Tier B rec): point-in-time constituent data source with exact vendor/dataset/cost.
DoD: new backtests carry the stamp; removed-ticker fixture retains history after universe refresh;
Tier B recommendation filed with concrete options.

## P2 — CLOSE THE LEARNING LOOP (this is "gets better over time")

### LRN-1 — Track MAE + entry/exit efficiency in the paper ledger  [Tier S]
Problem: max_favorable_excursion exists but max ADVERSE excursion does not — stop quality (the most
learnable parameter) cannot be evaluated; no exit-efficiency measure.
Fix: add max_adverse_excursion, exit_efficiency (realized/MFE), stop_distance_atr columns
(non-destructive ADD COLUMN) to paper trades in Postgres; compute daily from EOD bars.
DoD: columns exist; fixture trade's MAE/MFE/exit_efficiency computed correctly against known bars;
recompute idempotent; scorecard displays all three.

### LRN-2 — Wire `rule_changes_needed` / `jonah_research_priorities` to consumers  [Tier S]
Problem: weekly_scorecard generates lessons and research priorities that NOTHING consumes — the
learning loop is open.
Fix: (a) persist them to a lessons table (id, week, kind, text, status open/adopted/rejected, evidence);
(b) the daily optimizer reads open lessons in Phase 2 as planning candidates; (c) Jonah's deterministic
context script includes current jonah_research_priorities; (d) adopting/rejecting requires recorded
evidence.
DoD: scorecard run yields lessons rows; optimizer report provably lists open lessons among candidates;
Jonah context emits the priorities block; status transitions tested.

### LRN-3 — Expectation-vs-reality reconciliation  [Tier S]
Problem: paper outcomes are never compared to the backtest stats that justified the strategy; drift
between promised and realized edge is invisible.
Fix: nightly deterministic job comparing per-strategy realized paper metrics (win rate, avg R,
expectancy, realized slippage vs the assumed bps) against latest backtest OOS stats; write
strategy_drift rows; breach of a governed tolerance (e.g. realized expectancy < 50% of OOS over ≥20
trades) auto-demotes approved → candidate via the EXISTING monitoring demotion path, recording why.
DoD: drift fixture → demotion event with reason expectation_drift; within-tolerance fixture → no
action; realized-vs-assumed slippage reported.

### LRN-4 — Regime tagging for context, not prediction  [Tier S, later]
Deterministic regime labels (SPY 200-day trend up/down, realized-vol tercile) stamped on every
signal/setup/paper trade so the scorecard can slice performance by regime. LLMs may INTERPRET slices;
they never generate numeric edge.
DoD: labels computed deterministically from stored bars; every new setup row carries them; scorecard
groups by regime; recompute idempotent.

## P3 — SOURCE ROBUSTNESS

### DQ-4 — Cross-source close reconciliation  [Tier S]
Problem: multiple price sources exist but are never compared; a bad primary print flows through.
Fix: weekly no_agent job sampling N tier-1/2 tickers × last 5 closes across primary vs fallback
(respecting the fallback request budget); mismatch > 25bps → quality event severity review; persistent
mismatch → blocker.
DoD: injected-mismatch fixture produces the event; agreement fixture none; per-week request cap
respected in test; results in ledger.

### DQ-5 — Source failover policy + coverage metric  [Tier S config; any new vendor = Tier B]
Problem: fallback is disabled by default (max_tickers 0) and only 30-day; a primary outage stalls
freshness silently until the 5-day blocker.
Fix: enable bounded fallback for tier-1/2 (e.g. max 25 tickers/day) via governed config; ledger gains
ingest_source_mix (bars by source, fallback activations); report line on any fallback day. A paid
second source, if warranted, is a Tier B rec with vendor/plan/cost.
DoD: simulated primary failure → fallback fetches within cap and ledger shows source mix; cap tested.

### DQ-6 — Ledger truthfulness upgrades  [Tier S]
Add to the visible progress ledger: earnings_coverage_pct (DQ-2), unresolved_split_audits (DQ-1),
bar_quality_events_7d by severity (DQ-3), ingest_source_mix (DQ-5), survivorship_disclosure (VAL-4),
lessons_open (LRN-2), strategy_drift_flags (LRN-3). The ledger is the loop's memory — these make the
new rails visible and gradeable.
DoD: --json emits every new field correctly on fixtures; markdown renders them; optimizer KPI emission
includes them in loop_metrics.

## SEQUENCING & METRIC TARGETS (feed loop_metrics)
Order: DQ-1 → DQ-2 → DQ-3 → VAL-1 → LRN-1 → LRN-2 → VAL-2 → LRN-3 → DQ-4 → DQ-5 → VAL-3 → VAL-4 →
LRN-4 → DQ-6 (interleave DQ-6 fields as their producers land).
Targets: unresolved_split_audits=0; earnings_coverage_pct≥90 (tier 1/2); bar_quality_blockers_7d=0;
min_oos_trades_gate=on; lessons_open trending consumed (adopted+rejected > open); strategy_drift_flags
acted on within 1 cycle; ingest_source_mix shows fallback exercised ≥1×/month.
Reminder: no numeric thresholds above may be LOOSENED without human review (direction ratchet), and
none of this authorizes trade execution or strategy approval — those remain human-only.

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

## 2026-06-26 daily run

Snapshot/conflict check:

- Time: 2026-06-26 02:15 ET / 06:15 UTC.
- Git status: working tree already had pre-existing Hermes/Wolfy edits, including `wolfy/visible_progress_ledger.py`, alpha/scanner files, skill usage/reference files, and cron/jobs metadata. This run stays bounded and does not commit.
- Cron/processes: gateway and Postgres are running; no Hermes-managed background processes were active. A manual/idle `psql -d wolfy` session exists. Default cron has frequent near-term jobs: Jonah at 02:20, Mike environment repair at 02:26, storage/usage/embedding at 02:30, stale coordination cleanup at 02:32, safe autorepair at 02:35, allocator at 03:11, and Clerky/usage snapshot at 04:00. Market/report windows are later (08:00 pre-open, 10:00 scanner, 11:30 alpha report, 16:30+ EOD), so only lightweight non-mutating test/ledger work is safe.
- Recent cron output: no `/root/.hermes/logs/cron.log` file was present; default cron list shows most jobs OK, with the 2026-06-25 11:30 Alpha Search LLM report failing from a backend timeout/model issue. No current ingestion/report job was active at snapshot time.

### Candidate: visible-progress-ledger-regression-tests

- Status: implemented-bounded 2026-06-26.
- Owner/job: Wolfy daily optimization planner; supports future Clerky/activity/pre-open consumers of the visible progress ledger.
- Files/tables/jobs affected: added `/root/.hermes/wolfy/test_visible_progress_ledger.py`; no DB writes, no cron/job changes, no strategy approvals, no setup creation, and no trading action.
- Expected benefit: locks in the deterministic ledger's safety/visibility contract: EOD-only constitution, human approval gate, `candidate is not approved`, paper/accountability-no-live-trading wording, and core Markdown sections. This reduces the risk that future visibility edits accidentally imply actionability or drop key status sections.
- Risk: low. Test-only file plus this planning ledger; no market data jobs or schema maintenance.
- Rollback: delete `/root/.hermes/wolfy/test_visible_progress_ledger.py` and remove this entry.
- Tests/validation: Python compile check, targeted pytest for the new test file, JSON dry run of `visible_progress_ledger.py`, and Markdown dry run with `--limit 0`.
- Conflict result: safe to implement because it is a lightweight local test addition and read-only smoke; avoided files invoked by imminent cron jobs and avoided Postgres mutations/backtests.

### Candidate: trend-volume-strategy

- Status: deferred-next-slice.
- Owner/job: Wolfy EOD weekly research/backtest lane.
- Impact plan: improve `trend_volume_vol_regime` definition and run bounded walk-forward OOS only after depth/freshness/readiness/accountability gates are stable and tested.
- Expected benefit: advances the core EOD strategy toward candidate-quality validation while preserving candidate-not-approved and human approval gates.
- Risk: medium for this run because strategy/backtest edits and generated artifacts could exceed the two-file throttle and overlap frequent operations jobs.
- Rollback: revert strategy/backtest code changes and discard generated validation artifacts/rows.
- Tests/validation: targeted strategy tests, visible ledger readiness checks, then a bounded dry-run/OOS artifact.
- Conflict result: deferred; today's implementation strengthens the visibility regression net instead of running long strategy/data work near active operations windows.

### Candidate: paper-postgres

- Status: deferred.
- Owner/job: Wolfy accountability/paper ledger migration lane.
- Impact plan: inventory and migrate one remaining live paper-ledger SQLite consumer to Postgres-only behavior, guarded by `/root/.hermes/wolfy/check_postgres_requirements.py` if schema work is needed.
- Expected benefit: removes live SQLite dependence from paper portfolio/accountability reports.
- Risk: medium/high for this run because true migration may touch schema or multiple consumers.
- Rollback: revert consumer/schema changes; keep SQLite as legacy archive until explicit deletion approval.
- Tests/validation: Postgres guard before schema work, targeted ledger tests, representative context smoke, and visible ledger paper/accountability section.
- Conflict result: deferred for mutation; frequent jobs are active and today's safe scope is one test file plus the durable ledger.

## 2026-06-27 daily run

Snapshot/conflict check:

- Time: 2026-06-27 02:15 ET / 06:15 UTC.
- Git status: working tree already had many pre-existing Hermes/Wolfy edits and untracked files, including active Wolfy scripts, visible ledger/test files, tiered backfill helpers, skills/reference notes, profile scripts, and cron metadata. This run stays bounded and does not commit.
- Cron/processes: gateway and Postgres are running. A foreground `/root/.local/bin/hermes` process exists; no separate active Wolfy ingest/report/backfill worker was found. Near-term jobs at snapshot included Jonah at 02:20, stale coordination cleanup and safe autorepair around 02:22, storage/usage/embedding at 02:30, allocator/repair around 03:21-03:22, and Clerky/usage snapshot at 04:00. Market/report windows are not active now; next report/data windows are Monday. Only lightweight read-only helper work is safe.
- Recent cron output: default cron list reports recent OK runs for production jobs. Log search still shows older Jonah tool-query warnings from 2026-06-25; no current ingestion/report failure or active backfill conflict was identified.

### Candidate: visible-progress-ledger-tiered-data-load-status

- Status: implemented-bounded 2026-06-27.
- Owner/job: Wolfy daily optimization planner; supports visible-progress-ledger, trend-volume readiness, and tiered universe/backfill planning.
- Files/tables/jobs affected: modified `/root/.hermes/wolfy/visible_progress_ledger.py`; read-only joins across Postgres `universe` and `prices`; no DB writes, cron/job changes, strategy approvals, setup creation, broker access, or trading action. Updated this durable TODO ledger.
- Expected benefit: surfaces tier-by-tier EOD data coverage directly in the deterministic ledger: universe count, active/enabled count, tickers with prices, tickers with >=500 bars, missing-price count, and backfill-attention count. This makes it clear that blue_chip/etf_core are mostly loaded while large/mid/small tiers still need backfill before broader OOS validation.
- Risk: low. One read-only reporting helper change plus the ledger; no schema maintenance, no market-data pull, no long backtest, and no mutation of task/cron state.
- Rollback: revert the `visible_progress_ledger.py` change from this run and remove this entry.
- Tests/validation: `python3 -m py_compile /root/.hermes/wolfy/visible_progress_ledger.py`; `python3 /root/.hermes/wolfy/visible_progress_ledger.py --limit 0`; `python3 -m pytest /root/.hermes/wolfy/test_visible_progress_ledger.py -q`.
- Conflict result: safe to implement because it is read-only, completed outside market/report windows, and does not edit files invoked by the imminent no-agent operations jobs.

### Candidate: trend-volume-strategy

- Status: deferred-next-slice.
- Owner/job: Wolfy EOD weekly research/backtest lane.
- Impact plan: improve `trend_volume_vol_regime` definition and run bounded walk-forward OOS only after tiered data coverage/backfill attention is resolved enough for the target universe.
- Expected benefit: advances a core EOD strategy toward candidate-quality validation while preserving research-only/watch-only status until human approval.
- Risk: medium for this run because strategy edits, OOS artifacts, and any data pulls could exceed the two-file/time throttle and collide with frequent operations jobs.
- Rollback: revert strategy/backtest code and discard generated validation artifacts/rows.
- Tests/validation: targeted strategy tests, visible ledger data-load/depth/readiness checks, then a bounded dry-run/OOS artifact.
- Conflict result: deferred; today's safe implementation exposes the tiered data gap that should be closed before expanding OOS validation.

### Candidate: paper-postgres

- Status: deferred.
- Owner/job: Wolfy accountability/paper ledger migration lane.
- Impact plan: inventory and migrate one remaining live paper-ledger SQLite consumer to Postgres-only behavior, guarded by `/root/.hermes/wolfy/check_postgres_requirements.py` if schema work is needed.
- Expected benefit: removes live SQLite dependence from paper portfolio/accountability reports.
- Risk: medium/high for this run because true migration may touch schema or multiple consumers.
- Rollback: revert consumer/schema changes; keep SQLite as legacy archive until explicit deletion approval.
- Tests/validation: Postgres guard before schema work, targeted ledger tests, representative context smoke, and visible ledger paper/accountability section.
- Conflict result: deferred for mutation; frequent jobs are active and today's safe scope is one read-only helper change plus the durable ledger.

## 2026-06-29 orchestration refactor audit

Snapshot/conflict check:

- Time: 2026-06-29 21:58 EDT.
- Scope: read-only audit of default-profile cron list, Wolfy orchestration/context wrapper inventory, duplicated ticker constants, and current git state.
- Current state: script-only loops are active; several LLM/report jobs remain paused by provider usage limits. Working tree already contains many modified/untracked operational files, so broad refactors should be staged in narrow slices with compile/smoke verification.

### Candidate: orchestration-config-and-wrapper-consolidation

- Status: recommended-next-slice.
- Owner/job: Wolfy orchestration layer.
- Files likely affected: add a small shared module such as `/root/.hermes/wolfy/orchestration_config.py` and/or `/root/.hermes/wolfy/orchestration_runner.py`; update thin wrappers under `/root/.hermes/scripts/` and mirrored profile scripts only after tests pass.
- Evidence: the core EOD ticker universe is duplicated in `/root/.hermes/scripts/wolfy_eod_after_close_ingest.py` and `/root/.hermes/scripts/wolfy_eod_features_signals.py`; EOD shard ticker lists are hard-coded across five separate cron wrapper scripts; wrapper/profile copies have to be kept in sync manually.
- Expected benefit: one source of truth for core universe, shard definitions, default lookback, source provider, practical readiness threshold, JSON logging, exit-code conventions, and dry-run behavior. This reduces scheduler drift and makes future data-source/rate-limit changes safer.
- Risk: medium. Cron jobs call exact script names, so keep existing script filenames as stable thin shims and move only shared constants/runner logic behind them. Do not rewrite cron metadata or profile scripts in the same slice unless smoke tests prove the default wrappers work.
- Verification: `python3 -m py_compile` for touched modules/wrappers; dry-run EOD ingest wrapper; dry-run features/signals wrapper; no-agent wrapper smoke for one shard; `hermes --profile default cron list --all` after any cron-facing change.

### Candidate: orchestration-job-registry-visibility

- Status: recommended-after-wrapper-consolidation.
- Owner/job: Wolfy/Mike/Clerky operations visibility.
- Impact plan: create a read-only manifest/report that classifies cron jobs by lane (`data`, `signals`, `LLM-report`, `review`, `ops-watchdog`, `backfill`), mode (`no-agent` vs LLM), and pause reason if known.
- Expected benefit: answers “are we looping?” without manually parsing cron text; separates quota-paused LLM jobs from still-running deterministic backend jobs.
- Risk: low if read-only. No DB writes, no cron edits, no trading action.
- Verification: manifest output agrees with `hermes --profile default cron list --all` for active/paused counts and script paths.

### Candidate: autorepair-decomposition

- Status: defer-until-tests-expanded.
- Evidence: `mike_safe_autorepair.py` is currently over 1,100 lines and copied across global/default/Mike/Clerky script locations.
- Expected benefit: split checks from repairs, separate wrapper-sync checks from DB/cron health checks, and make each operation idempotent/read-only unless explicitly repairing.
- Risk: higher than wrapper consolidation because safe-autorepair is a live guardrail. Do not refactor this before adding focused tests and confirming all profile copies are synchronized.

### Implementation update: orchestration-config-and-wrapper-consolidation

- Status: implemented-bounded 2026-06-29.
- Files affected: added `/root/.hermes/wolfy/orchestration_config.py` and `/root/.hermes/wolfy/orchestration_runner.py`; refactored `/root/.hermes/scripts/wolfy_eod_after_close_ingest.py`, `/root/.hermes/scripts/wolfy_eod_features_signals.py`, and `/root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_{1..5}.py` into stable thin cron shims.
- Behavior preserved: cron-facing script filenames remain unchanged; EOD source remains Massive by default; lookback remains 730 days; shard ticker lists are unchanged; shard wrappers still pass `--no-validate`; dry-run wrappers remain no-write.
- Expected benefit: one source of truth for core universe, EOD shard groups, default source, default lookback, and practical readiness threshold; lower scheduler drift and less manual wrapper/profile sync risk.
- Verification: Python compile passed for config, runner, after-close wrapper, five shard wrappers, and features/signals wrapper; `/root/.hermes/wolfy/test_eod_after_close_ingest_wrapper.py` passed with 2 tests; dry-run Yahoo ingest returned 3 SPY bars and no writes; dry-run features/signals returned no-write approved-gate JSON; shard import/monkeypatch smoke confirmed all five ticker groups and exit code 0.
- Trading boundary: no DB writes from smoke dry-runs except read-only Postgres signal-gate reads; no setup creation, no strategy approval, no broker access, no trading action.

## 2026-06-30 one-time orchestration bootstrap

- FACT: Paused seven token-heavy LLM cron jobs: Jonah `07253dc09350`, Clerky `a739dac0d264`, Wolfy EOD `ba183091b5c0`, Sentinel `ce017fe2f3fb`, Yang `de6f05f10cb5`, Alpha Search `4452bdae4553`, Mike repair loop `fdfd5b53b5d5`. Optimizer `92f31b95fccc` remained active for 2026-07-01 02:15 ET.
- OWS-1 complete: added deterministic `wolfy/guardian/budget_gate.py`. Verified over-cap simulation produced `BUDGET=block` with exit 1; under-cap simulation produced `BUDGET=ok` with exit 0; real state blocks on `codex_usage_limited`. Commit: `87043a2`.
- OWS-2 complete: added deterministic `wolfy/guardian/config_guardian.py` and `wolfy/test_config_guardian.py`. Test passed: broken config + expired probation restores known-good and logs rollback. Real restore proof succeeded: deliberately broken `/root/.hermes/config.yaml` was restored from `/root/.hermes/wolfy/guardian/known_good/20260701T012552Z`; `hermes cron list` then exited 0. Commit: `59b8214`.
- OWS-3 partial/installed on probation: set `cron.max_parallel_jobs=1` and `kanban.max_in_progress_per_profile=1` using self-modification protocol. Snapshot: `/root/.hermes/wolfy/guardian/known_good/20260701T012621Z`. Probation expires `2026-07-01T06:30:00Z`, after the next optimizer run. Commit: `7f4b39a`.
- DECISION: left all seven heavy LLM jobs paused because the real budget gate currently reports `BUDGET=block codex_usage_limited`; re-enabling would immediately risk another 429. Do not restore Jonah to `*/20`.
- KPIs recorded to `loop_metrics`: `usage_headroom_pct`, `tokens_today`, `gateway_healthy`, `config_rollbacks`, `parallel_jobs_cap`.
- LESSON: proactive gates and rollback proof must exist before schedule/config autonomy; current budget status says no LLM re-enable yet.
- NEXT ACTION: daily optimizer should confirm OWS-3 probation after its 02:15 run, then wire paused LLM jobs to consult `budget_gate.py` and re-enable only low-frequency jobs while Jonah remains paused or hourly.
- OWS-2 operationalized: added no-agent cron `e55c9cc39d8d` (`Wolfy config guardian auto-restore`) via `scripts/wolfy_config_guardian.sh`, scheduled every 15m, verified script exit 0 with `GUARDIAN=ok ... probation_active`.

## 2026-07-01 daily optimizer plan-only run

- Time: 2026-07-01 02:15 ET / 06:15 UTC.
- Budget gate: `python wolfy/guardian/budget_gate.py` returned `BUDGET=block codex_usage_limited` (exit 1), so this run followed the PLAN-ONLY rule: review/state/KPI updates only, no code/config/cron implementation.
- Guardian: `python wolfy/guardian/config_guardian.py --skip-cli` returned `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;probation_active` (exit 0). Full `hermes cron list` also exited 0.
- OWS-3 probation remains active until `2026-07-01T06:30:00Z`; config values were read as `cron.max_parallel_jobs=1` and `kanban.max_in_progress_per_profile=1`. Do not make a second orchestration/config change until probation is resolved by a later run/guardian cycle.
- State: created/claimed task `3171` and run `194909`; recorded `jobs_skipped_by_budget=1`, `parallel_jobs_cap=1`, `human_approval_pending`, and recent `config_rollbacks` metrics.
- NEXT ACTION: after budget recovers and OWS-3 probation clears, implement the next bounded control-plane slice: wire/review paused LLM job wrappers for budget-gate no-op behavior and only then consider low-frequency re-enable; keep Jonah off `*/20` or move to hourly per OWS-4.

## 2026-07-01 one-time backlog installation close-out

- FACT: Installed the user-approved Data & Learning Backlog immediately after Operating constraints. Commit `ca42f85` (`docs: add Wolfy data learning backlog`).
- FACT: Added `/root/.hermes/wolfy/DATA_QUALITY_STANDARDS.md`. Commit `5c169d1` (`docs: add Wolfy data quality standards`).
- FACT: Persisted 31 Postgres `agent_tasks` rows as `agent_name=wolfy`, `task_type=optimization`, source fingerprints `user-approved-20260701-*`; counts: DQ=6, VAL=4, LRN=4, ARCH=6, R=6, WATCH=5. These are queued planning candidates only; no DQ/VAL/LRN/ARCH/R/WATCH implementations were performed in this run except the allowed watchdog state repair.
- FACT: Minimal provider health probe succeeded (`hermes chat -q 'Reply exactly: OK' --toolsets safe --source wolfy-health-probe -Q` returned `OK`, session `20260701_232729_cac83e`).
- FACT: Watchdog state before repair claimed `limited_active=true` with quota detail `device_code rate-limited usage_limit_reached (429)` while provider health was OK. One-time repair backed up state to `/root/.hermes/wolfy/usage_limit_watchdog_state.json.bak-20260701T2327-one-time-repair`, set `limited_active=false`, cleared `limit_resets_at`, recorded the stale-evidence repair reason, and removed enabled optimizer job `92f31b95fccc` from `paused_llm_jobs`. Remaining paused-by-watchdog state entries: Jonah `07253dc09350`, Alpha Search `4452bdae4553`, Clerky `a739dac0d264`, Wolfy EOD `ba183091b5c0`, Sentinel `ce017fe2f3fb`, Yang `de6f05f10cb5`, Mike repair `fdfd5b53b5d5`.
- JUDGMENT: Top current risks are (1) split-adjustment basis corruption before DQ-1, (2) empty earnings calendar causing event-safety false clears before DQ-2, and (3) quota watchdog stale-log/self-feedback false positives corrupting budget orchestration before WATCH-1/WATCH-2/WATCH-4.
- RECOMMENDATIONS FOR HUMAN: expect Tier B asks from R-1 point-in-time constituents, R-2 earnings/events source if the current data plan lacks it, R-3 fallback LLM provider/API key, and any new package/vendor for R-4 backtester validation; options paper support should likely defer until equity strategies have approved evidence.
- NEXT ACTION: the daily optimizer's next implementation task is DQ-1 unless Priority-1 data health is broken; WATCH-1 should run before or alongside it if quota state regresses.

## 2026-07-08 daily optimizer implementation run

- Time: 2026-07-08 02:15 ET / 06:15 UTC.
- Budget gate: `python3 wolfy/guardian/budget_gate.py` returned `BUDGET=ok tokens_today=85746 cap=200000 headroom_pct=57.13`, so implementation was allowed.
- Review finding: the prior probation `OWS-1 bounded slice: Jonah cron wrapper budget wake gate` expired and `config_guardian.py` restored known-good config/jobs at 2026-07-08T06:16:31Z. Treat that exact wrapper-only attempt as a failed pattern; do not retry it identically.
- Implemented replacement bounded slice: added the budget wake gate inside `/root/.hermes/wolfy/hourly_knowledge_context.py` before Jonah context/task-claim output. When `budget_gate.py` blocks, Jonah now prints `skipped: budget ...` and the final JSON line `{"wakeAgent": false, "reason": "budget"}`, which Hermes cron parses to skip the LLM run with exit 0.
- Snapshot for self-modification protocol: `/root/.hermes/wolfy/guardian/known_good/20260708T061822Z`.
- Validation: py_compile passed; simulated over-cap wrapper run emitted `skipped: budget` + `wakeAgent=false` and exited 0; normal smoke wrapper emitted `Budget gate: BUDGET=ok`, Jonah context, and `SMOKE=true`; config YAML and cron JSON parsed; `hermes cron list` succeeded; `config_guardian.py` returned `GUARDIAN=ok ... probation_active`.
- Probation: `/root/.hermes/wolfy/guardian/probation.json` expires at 2026-07-09T06:15:00Z.
- NEXT ACTION: next optimizer run should confirm the probation if Jonah/optimizer schedule stayed healthy; if so, continue OWS-1 wiring for remaining LLM jobs or OWS-4 cadence reduction, one reversible change at a time.

## 2026-07-02 daily optimizer plan-only run

- Time: 2026-07-02 02:15 ET / 06:15 UTC.
- Budget gate: `python wolfy/guardian/budget_gate.py` returned `BUDGET=block token_cap_exceeded tokens_today=840644 cap=200000`; per optimizer rules this run did review/state/KPI updates only and made no code/config/cron implementation change.
- Guardian: `python wolfy/guardian/config_guardian.py` returned `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;hermes_cron_list_ok;no_probation`; no probation marker existed.
- Review finding: OWS-1 is not fully wired despite `budget_gate.py` existing. `cron/jobs.json` search showed optimizer prompt mentions the gate, but Jonah and other non-`no_agent` LLM jobs do not contain `budget_gate`/`skipped: budget`; Jonah continued running every 20 minutes while the budget gate was over cap.
- State: created Postgres `agent_tasks` id `3243` (`Complete OWS-1 budget gate wiring for LLM cron jobs`) and `agent_runs` id `195339`; recorded `jobs_skipped_by_budget=1`, `parallel_jobs_cap=1`, `max_turns=90`, `gateway_healthy=1`, `config_rollbacks=0`, `human_approval_pending=0` metrics.
- NEXT ACTION: once budget headroom is OK, complete OWS-1 before OWS-4/OWS-5: snapshot config/jobs, wire Jonah and remaining LLM cron jobs to consult `wolfy/guardian/budget_gate.py` and print `skipped: budget` before any LLM spend, verify simulated over-cap no-ops, then validate `hermes cron list` and set probation if jobs/config changed.

## 2026-07-09 daily optimizer plan-only run

- Time: 2026-07-09 02:15 ET / 06:15 UTC.
- Budget gate: `python3 wolfy/guardian/budget_gate.py` returned `BUDGET=block token_cap_exceeded tokens_today=279759 cap=200000`; per optimizer rules this run made no code/config/cron implementation change.
- Guardian/probation: the prior Jonah context budget gate probation expired at this run boundary. `config_guardian.py` restored the latest known-good snapshot `/root/.hermes/wolfy/guardian/known_good/20260709T060157Z` and cleared probation. The restored tree still contains the Jonah context budget gate; `python3 scripts/wolfy_hourly_knowledge_context.py` emitted `skipped: budget ...` and `{"wakeAgent": false, "reason": "budget"}` with exit 0.
- State: recorded plan-only task/run in Postgres and KPI rows for budget skip, token headroom, gateway health, config rollback, max_turns, and concurrency cap.
- LESSON: optimizer probation expiry equals scheduled start time, so a normal run can arrive after expiry and let the guardian clear probation first. Do not treat this specific restoration as functional regression because the protected Jonah gate remained present and verified.
- NEXT ACTION: when budget recovers, continue OWS-1 wiring for remaining LLM jobs or choose OWS-4 Jonah cadence reduction, one reversible change at a time; consider a later bounded guardian improvement to add a small confirmation grace window if repeated false rollbacks occur.

## 2026-07-11 daily optimizer plan-only run

- Time: 2026-07-11 02:16 ET / 06:16 UTC.
- Budget gate: `python3 wolfy/guardian/budget_gate.py` returned `BUDGET=block token_cap_exceeded tokens_today=309142 cap=200000`; per optimizer rules this run made no code/config/cron implementation change.
- Guardian/probation: no probation marker existed; `python3 wolfy/guardian/config_guardian.py` returned `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;hermes_cron_list_ok;no_probation` and recorded `gateway_healthy=1`, `config_rollbacks=0`.
- State: created/claimed Postgres task `3544` (`Plan-only optimizer budget block 2026-07-11`) and run `295717`; recorded `jobs_skipped_by_budget=1`, `parallel_jobs_cap=1`, `max_turns=90`, `human_approval_pending`, and trailing `iteration_success_rate` metrics.
- NEXT ACTION: wait for budget headroom to recover, then implement one bounded Tier S slice only. Preferred next slice remains OWS-1/OWS-4 control-plane work: finish budget-gate no-op coverage for remaining LLM jobs or reduce Jonah cadence to hourly under the self-modification protocol.

## 2026-07-12 daily optimizer plan-only run

- Time: 2026-07-12 02:15 ET / 06:15 UTC.
- Budget gate: `python wolfy/guardian/budget_gate.py --no-record` returned `BUDGET=block token_cap_exceeded tokens_today=337507 cap=200000` (exit 1), so the optimizer followed the PLAN-ONLY rule: review/state/KPI updates only, no code/config/cron implementation.
- Guardian/probation: no probation marker existed; `python wolfy/guardian/config_guardian.py --skip-cli` returned `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;no_probation` (exit 0), and `hermes cron list` succeeded with optimizer `92f31b95fccc` still active.
- State: created/claimed Postgres task `3545` (`Plan-only optimizer budget block 2026-07-12`) and run `299774`; visible ledger showed 27 active cron jobs, no paused cron jobs, `parallel_jobs_cap=1`, `max_turns=90`, and `human_approval_pending=0`.
- NEXT ACTION: wait for budget headroom to recover, then implement exactly one bounded Tier S control-plane slice. Preferred next slice remains OWS-1/OWS-4: finish budget-gate no-op coverage for remaining LLM jobs or reduce Jonah cadence to hourly under the self-modification protocol.

## 2026-07-15 daily optimizer plan-only run

- Time: 2026-07-15 02:15 ET / 06:15 UTC.
- Budget gate: `python3 wolfy/guardian/budget_gate.py` returned `BUDGET=block token_cap_exceeded tokens_today=323156 cap=200000` (exit 1), so this run followed the PLAN-ONLY rule: review/state/KPI updates only, no code/config/cron implementation.
- Guardian/probation: no probation marker existed; `python3 wolfy/guardian/config_guardian.py --skip-cli` returned `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;no_probation` (exit 0), and `hermes cron list` succeeded with optimizer `92f31b95fccc` still active.
- State: created/claimed/completed Postgres task `3558` (`Plan-only optimizer budget block 2026-07-15`) and run `311571`; recorded KPI rows for `tokens_today=323156`, `usage_headroom_pct=-61.578`, `jobs_skipped_by_budget=1`, `gateway_healthy=1`, `config_rollbacks=0`, `max_turns=90`, `parallel_jobs_cap=1`, `human_approval_pending=0`, `iteration_success_rate=0.9783783783783784`, and `regressions_introduced=0`.
- NEXT ACTION: wait for budget headroom to recover, then implement exactly one bounded Tier S control-plane slice. Preferred next slice remains queued task `3546` / OWS-4: reduce Jonah cadence from `*/20` to hourly under the self-modification protocol, or finish OWS-1 no-op coverage for remaining LLM jobs if that is higher leverage when headroom returns.

## 2026-07-16 daily optimizer plan-only run

- Time: 2026-07-16 02:16 ET / 06:16 UTC.
- Budget gate: `python3 wolfy/guardian/budget_gate.py` returned `BUDGET=block token_cap_exceeded tokens_today=276666 cap=200000` (exit 1), so this run followed the PLAN-ONLY rule: review/state/KPI updates only, no code/config/cron implementation.
- Guardian/probation: no probation marker existed; `python3 wolfy/guardian/config_guardian.py` returned `GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;hermes_cron_list_ok;no_probation` (exit 0), and `hermes cron list` succeeded with optimizer `92f31b95fccc` still active.
- State: completed plan-only run `315551`; recorded KPI rows for tokens/headroom, budget skip, guardian/gateway health, max_turns, concurrency cap, data freshness/depth, strategy counts, trailing iteration success, and repo size.
- NEXT ACTION: when budget headroom recovers, execute exactly one Tier S control-plane slice. Preferred queued task remains `3546` / OWS-4: reduce Jonah cadence from `*/20` to hourly under the self-modification protocol; otherwise finish remaining OWS-1 no-op coverage if budget-gate gaps are found.
