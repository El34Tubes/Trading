# Wolfy Recommendation Engine Agentic Implementation Plan

> **For Hermes:** Use subagent-driven-development / Wolfy optimizer loop to implement this plan task-by-task. Do not approve any strategy without explicit human approval.

**Goal:** Move Wolfy from scanner/research-only outputs to accountable EOD paper-trade recommendations by adding one narrow deterministic strategy, validating it, and wiring approved-strategy-gated setup/recommendation generation into the existing agentic loop.

**Architecture:** Keep the LLM out of signal generation. Deterministic Python modules create strategy rows, signals, validation reports, setup rows, recommendation rows, and paper-ledger updates in Postgres. LLM agents only interpret/rank/explain deterministic rows and Sentinel/Yang review before anything becomes a paper-trade candidate. The first target strategy is `liquid_rs_breakout_continuation`: long-only, EOD-only, broad/current Wolfy universe with safety/data gates, 5-day high breakout, 20-day relative strength vs SPY, volume confirmation, next-session trigger, and underlying setup-accuracy review.

**Tech Stack:** Python 3, Postgres `wolfy`, psycopg, pytest, Hermes cron, existing Wolfy files under `/root/.hermes/wolfy/` and wrappers under `/root/.hermes/scripts/`.

---

## Non-negotiable operating rules

1. **No auto-execution:** no broker integration, no money movement, no order placement.
2. **EOD-only:** all candidate setups use closing data and are for next-session human review/execution.
3. **Human approval gate:** implementation may promote a strategy to `candidate` after deterministic validation, but only the user can mark `strategies.status='approved'`.
4. **Approved-strategy gate:** rows in `recommendations` with actionable/paper-candidate status require:
   - `strategies.status='approved'`
   - deterministic `signals` row
   - deterministic `setups` row
   - stop/invalidation
   - sizing for $5,000 paper account
   - max 3 concurrent positions gate
   - Sentinel and Yang review path.
5. **Watch-only until approved:** any research-only or candidate strategy may generate signals and validation reports, but not capital/paper recommendation rows.
6. **Quiet nights are valid:** 0 setups is correct when gates fail.

---

## Current baseline

Observed before this plan:

- `agent_tasks`: blocked cleared to 0; queued remains active.
- `strategies`: `pead`, `trend_volume_vol_regime`, `sector_cross_sectional_momentum` are all `research_only`.
- Latest OOS results for existing strategies are weak or empty, so none should be approved.
- `signals` exist, `setups=0`, `paper_trades=0`, no pending recommendations.
- Price/features path is live; latest core date was `2026-07-15`, scanner latest date `2026-07-16`.

---

## Strategy specification: `liquid_rs_breakout_continuation`

### Intent

Find broad-current-universe U.S. stocks/ETFs showing 20-day relative strength versus SPY that break a 5-day high on volume from near highs, then propose next-session paper candidates only after validation, human strategy approval, and Sentinel/Yang review. The strategy is designed for 1–2 week bullish defined-risk options ideas, with equity/ETF fallback labeled when used.

### Deterministic signal rules, v1

A ticker qualifies on signal date `dt` if all are true:

1. **Universe/safety gate**
   - Use the broad/current active/enabled Wolfy universe across tiers.
   - Enforce data quality, sufficient history, Robinhood/practical tradability, and foreign/government-interference/manipulation-risk gates before any setup/recommendation/paper trade.
   - Do not exclude by tier alone; penalize lower quality/liquidity in ranking.
2. **History gate**
   - Ticker has enough bars for 20-day RS, 5-day breakout/low, ATR, and fast/slow moving averages; prefer `DEPTH_READY_BARS` / 495 bars for validation.
3. **Trend gate**
   - `close > sma_fast` and `sma_fast >= sma_slow` where available.
   - If moving-average fields differ, compute deterministic 20/50-day equivalents from `prices`.
4. **Relative-strength gate**
   - Ticker 20-trading-day return must be greater than SPY 20-trading-day return.
5. **Breakout trigger**
   - `close_today > prior_5_day_high` using completed bars before `dt`.
   - Recommendation is for next-session trigger/review; do not chase an opening gap more than `0.5 * ATR` above breakout trigger.
6. **Near-high/tightness gate**
   - Prior close or current close is within 5% of the recent high, proving the name is not deeply broken.
7. **Volume confirmation**
   - `vol_ratio >= 1.2` on breakout.
8. **Stop/invalidation**
   - Default stop/invalidation is below prior 5-day low.
9. **Profit/time plan**
   - Intended max hold is 10 trading days.
   - Take partial at 1.5R and trail the remainder using structure/ATR/time-stop rules.
10. **Options note**
   - Preferred expression is a 2–3 week slightly OTM call spread.
   - Options liquidity is not a hard gate by user direction; surface OI/volume/spread as informational and `user_to_evaluate_manually` when data exists.
11. **Event/regime gates**
   - Known earnings/events are reviewed by Sentinel case-by-case.
   - Broad market regime is a soft Sentinel gate in v1, not a deterministic hard block.

### Signal raw payload

Each signal row should include enough facts for review without recomputing:

```json
{
  "strategy": "liquid_rs_breakout_continuation",
  "close": "123.45",
  "prior_5d_high": "122.80",
  "prior_5d_low": "116.10",
  "sma_fast": "120.25",
  "sma_slow": "114.70",
  "atr": "2.40",
  "atr_pct": "0.0194",
  "ticker_return_20d": "0.082",
  "spy_return_20d": "0.031",
  "rs_excess_20d": "0.051",
  "vol_ratio": "1.30",
  "within_5pct_recent_high": true,
  "preferred_instrument": "2-3wk slightly OTM call spread",
  "option_liquidity_hard_gate": false,
  "option_liquidity_note": "user_to_evaluate_manually",
  "gate_status": "research_only|candidate|approved",
  "reason": "20d RS leader breaking prior 5d high on confirmed volume near highs"
}
```

---

## Implementation tasks

### Task 1: Add strategy seed and unit test

**Objective:** Ensure `liquid_rs_breakout_continuation` exists in `strategies` as `research_only` and cannot be auto-approved.

**Files:**
- Modify: `/root/.hermes/wolfy/eod_signals.py`
- Modify: `/root/.hermes/wolfy/test_eod_signals.py`

**Steps:**
1. Add `liquid_rs_breakout_continuation` to `DEFAULT_STRATEGIES` with setup type `rs_breakout_continuation` and notes stating human approval required.
2. Update `_restore_default_strategy_statuses()` in tests to include the new strategy.
3. Add/extend a test asserting all seeded strategies, including the new one, have `status='research_only'` and `gate_status='research_only'` in raw signal output.
4. Run:
   ```bash
   cd /root/.hermes/wolfy
   python3 -m pytest test_eod_signals.py -q
   ```
5. Expected: tests pass; DB strategy row exists but is not approved.

**DoD:** Strategy row exists as `research_only`; no setup/recommendation can be produced from it without approval.

---

### Task 2: Add deterministic RS breakout signal generator

**Objective:** Generate research-only `signals` rows for `liquid_rs_breakout_continuation` from existing `prices` and `features`.

**Files:**
- Modify: `/root/.hermes/wolfy/eod_signals.py`
- Modify: `/root/.hermes/wolfy/test_eod_signals.py`

**Steps:**
1. Add `_generate_liquid_rs_breakout(conn, *, tickers, signal_dt, strategies, params=None)`.
2. Query ticker and SPY `prices` plus `features` for `signal_dt` and prior bars needed for 5-day breakout/low, 20-day RS, ATR, MAs, volume, and near-high checks.
3. Use only deterministic values already stored or computed from `prices`.
4. Upsert `signals` with raw payload fields listed above.
5. Add synthetic fixture test with 20-day RS > SPY, 5-day high breakout, vol_ratio >= 1.2, within 5% high, valid trend, stop below prior 5-day low.
6. Add negative tests for no RS, no breakout, low volume, deep breakdown, stop missing, and too-large gap-chase cases.
7. Run:
   ```bash
   cd /root/.hermes/wolfy
   python3 -m pytest test_eod_signals.py::test_generate_liquid_rs_breakout_continuation_signal -q
   python3 -m pytest test_eod_signals.py -q
   ```

**DoD:** Signal generation is deterministic, idempotent, and writes no setups while strategy is research-only.
---

### Task 3: Apply broad-universe recommendation gates

**Objective:** Honor the user's broad/current-universe choice while preventing low-quality names from contaminating recommendations.

**Files:**
- Modify or create helper in `/root/.hermes/wolfy/eod_signals.py` or `/root/.hermes/wolfy/orchestration_config.py`
- Test: `/root/.hermes/wolfy/test_eod_signals.py`

**Steps:**
1. Add a helper that returns recommendation-v1 tickers from the current active/enabled universe across all tiers.
2. Enforce liquidity, adequate history, data-quality, Robinhood/practical tradability, and manipulation/government-interference risk gates before any setup/recommendation/paper trade.
3. Do not exclude small/mid/unassigned tiers solely by tier if they pass the gates; rank/penalize lower quality/liquidity appropriately.
4. Add tests proving broad-universe tickers can be considered, while illiquid, stale, manipulation-risk, or insufficient-history tickers are blocked.
5. Run relevant tests.

**DoD:** First recommendation strategy can search the broad current universe, but only gated, liquid, data-ready, practical names can advance.

---

### Task 4: Extend backtest evidence gates before candidate promotion

**Objective:** Prevent weak or thin strategies from becoming candidates.

**Files:**
- Modify: `/root/.hermes/wolfy/eod_backtest.py`
- Modify: `/root/.hermes/wolfy/test_eod_backtest.py`

**Steps:**
1. Add governed minimums: OOS Sharpe threshold `>= 0.75`, OOS max drawdown `< 15%`, dynamic strategy-frequency-based IS/OOS trade-count floors, and conservative cost/slippage floors.
2. Store failure reasons in `backtests.report` JSON, including Sharpe, drawdown, trade-count, turnover, and data-quality failures.
3. Ensure `survives_oos=false` if evidence is too thin even when Sharpe is high.
4. Let strategy-specific validation report win-rate vs reward-asymmetry tradeoff rather than forcing a global preference.
5. Run:
   ```bash
   cd /root/.hermes/wolfy
   python3 -m pytest test_eod_backtest.py -q
   ```

**DoD:** No strategy can pass validation on a tiny or lucky sample.

---

### Task 5: Run validation for `liquid_pullback_continuation`

**Objective:** Produce real backtest/walk-forward evidence on stored Postgres bars.

**Files:**
- Possibly modify CLI in `/root/.hermes/wolfy/eod_backtest.py`
- Output: Postgres `backtests`, `research_log`, `strategies.latest_oos_*`

**Steps:**
1. Generate historical signals for the v1 universe over the available historical window.
2. Run backtest with conservative slippage/costs.
3. Store backtest report JSON with window, IS/OOS Sharpe, OOS CAGR, max drawdown, turnover, IS/OOS trade counts, survivorship disclosure, and fail/pass reasons.
4. If it passes, set `strategies.status='candidate'`, never `approved`.
5. If it fails, keep `research_only` and create a follow-up task describing the failure mode.

**DoD:** Strategy is either `candidate` with real evidence, or remains `research_only` with a clear reason.

---

### Task 6: Add approved-gated recommendation writer from setups

**Objective:** Convert approved, reviewed deterministic setups into `recommendations` rows in Postgres.

**Files:**
- Create or modify: `/root/.hermes/wolfy/eod_recommendations.py`
- Test: `/root/.hermes/wolfy/test_eod_recommendations.py`
- Integrate carefully with existing `/root/.hermes/wolfy/recommendation_logger.py` only if it is Postgres-safe; do not revive live SQLite.

**Steps:**
1. Implement `ensure_recommendation_schema(conn)` only with non-destructive columns if needed.
2. Implement `create_recommendations_from_setups(conn, for_session, dry_run=False)`.
3. Require `strategies.status='approved'`.
4. Require setup status `pending_review` or final approved review state per Sentinel/Yang schema.
5. Populate `recommendations` fields: ticker, action, recommendation_type, thesis, setup_type, entry_trigger, stop, target, risk_reward, confidence, position_size_suggestion, holding_period, status, notes.
6. Notes JSON must include `strategy_id`, `setup_id`, `signal_dt`, FACT/JUDGMENT split, no-auto-execution language.
7. Add tests proving research-only/candidate strategies cannot create recommendations.
8. Run tests.

**DoD:** Approved strategy + deterministic setup is the only path to actionable recommendation rows.

---

### Task 7: Wire Sentinel/Yang review into recommendation promotion

**Objective:** Ensure recommendations become paper candidates only after risk and technical review.

**Files:**
- Review existing: `/root/.hermes/wolfy/test_sentinel_reviews.py`, `/root/.hermes/wolfy/test_yang_technical_reviews.py`
- Modify: Sentinel/Yang context or persistence helpers as needed.

**Steps:**
1. Confirm where `recommendation_reviews` and Yang outputs are stored.
2. Define status transitions:
   - setup `pending_review`
   - Sentinel `approved|needs_revision|rejected`
   - Yang `technically_valid|wait|invalid`
   - recommendation `pending_review|watching|paper_candidate|rejected|needs_revision`
3. Add tests proving a candidate missing stop, earnings coverage, or Yang technical confirmation cannot become `paper_candidate`.
4. Options liquidity is **not** a hard block by user direction; include option liquidity fields/warnings when available so the user can evaluate at manual trade-placement time.
5. Run review tests.

**DoD:** No recommendation reaches paper-candidate status without deterministic setup support and review gates; options liquidity is surfaced as information, not used as a hard gate.

---

### Task 8: Add Postgres paper-ledger auto-logging gate

**Objective:** Auto-log approved paper trades to the Postgres `paper_trades` table after both Sentinel and Yang approve; do not use SQLite or any broker/live-execution path.

**Files:**
- Create or modify: `/root/.hermes/wolfy/eod_paper_trades.py`
- Review/modify: `/root/.hermes/wolfy/test_paper_portfolio.py`
- Create or modify: `/root/.hermes/wolfy/test_eod_paper_trades.py`
- Do **not** route this live path through legacy SQLite helpers such as `recommendation_logger.py` or `yang_technical_reviews.py`; if those are needed, migrate/bridge them to Postgres first.

**Steps:**
1. Implement `ensure_paper_trade_schema(conn)` as non-destructive Postgres schema maintenance only.
2. Implement `auto_log_approved_paper_trades(conn, for_session, dry_run=False)` that reads Postgres recommendations/setups/reviews and writes Postgres `paper_trades`.
3. Require all gates before insert:
   - recommendation status is paper-candidate/approved-for-paper equivalent,
   - originating strategy is `approved`,
   - deterministic setup and signal ids are present in recommendation notes,
   - Sentinel review approved,
   - Yang technical review approved/technically valid,
   - stop/invalidation, target/exit, entry trigger, instrument, and risk amount are present,
   - max 3 open paper positions is not exceeded,
   - no shorts/live execution/broker fields.
4. Use the user's paper settings: `$5,000` account, `2%` risk/trade, max `3` open positions, defined-risk options preferred when available, daily summary only. Do not require options liquidity for paper logging; store liquidity/OI/volume/spread information in notes if available and mark it `user_to_evaluate_manually`.
5. Insert one row per accepted paper trade into Postgres `paper_trades` with `recommendation_id`, ticker, planned entry/stop/target, quantity/risk metadata, instrument, status `planned` or `open` according to the paper execution model, and notes JSON containing `source='postgres_eod_recommendation_engine'`, `setup_id`, `signal_id`, `strategy_id`, `sentinel_review_id`, `yang_review_id`, `option_liquidity_user_evaluated=true`, and `no_live_execution=true`.
6. Make insertion idempotent: repeated cron runs must not duplicate a paper trade for the same recommendation/setup.
7. Add tests proving:
   - a fully reviewed approved recommendation inserts exactly one Postgres `paper_trades` row,
   - rerun is idempotent,
   - missing Sentinel/Yang approval blocks insertion,
   - research-only/candidate strategies block insertion,
   - max 3 open positions blocks insertion,
   - no SQLite database file is touched.

**DoD:** Paper trading is logged in Postgres `paper_trades` only, automatically after Sentinel + Yang approval, with idempotent tests and no SQLite fallback/live execution path.

---

### Task 9: Make the loop visible

**Objective:** Ensure the user can see progress toward recommendations without reading raw cron logs.

**Files:**
- Modify: `/root/.hermes/wolfy/visible_progress_ledger.py`
- Modify tests: `/root/.hermes/wolfy/test_visible_progress_ledger.py`

**Steps:**
1. Add recommendation-engine section:
   - pullback strategy status
   - latest signal count
   - latest validation verdict
   - candidate/approved gate
   - setups pending review
   - recommendations pending/paper_candidate
   - next blocked gate.
2. Keep language explicit: `candidate is not approved` when relevant.
3. Add render regression tests.
4. Run visible ledger tests and script.

**DoD:** Ledger reports exactly why recommendations are or are not appearing.

---

### Task 10: Cron/agentic loop integration

**Objective:** Let Wolfy continue progressing automatically in bounded safe slices.

**Files:**
- `/root/.hermes/wolfy/optimization_todo.md`
- Postgres `agent_tasks`
- Existing cron job: `Wolfy daily optimization planner and implementer`

**Steps:**
1. Insert this plan's tasks into Postgres `agent_tasks` with stable `source_fingerprint` values.
2. Prioritize tasks in order: seed -> signal -> universe -> validation gates -> validation run -> recommendation writer -> review integration -> paper gate -> ledger.
3. Daily optimizer should consume at most one implementation slice per run under budget gate.
4. If budget gate blocks, it should leave the next task queued and report plan-only.
5. Do not mutate cron schedules for this project unless guardian/probation protocol permits it.

**DoD:** `agent_tasks` contains durable recommendation-engine tasks and the daily optimizer has an explicit next task.

---

## Recommendation success evaluation

Because the user may place trades manually at unknown prices/times, Wolfy must evaluate **setup accuracy**, not the user's realized option P/L.

For each approved/logged recommendation, evaluate the underlying ticker over the intended horizon:

- Did the underlying continue higher after the EOD signal/next-session trigger window?
- Maximum favorable excursion over the 10-trading-day horizon.
- Maximum adverse excursion over the 10-trading-day horizon.
- Whether the underlying hit the planned 1.5R target before invalidation.
- Whether the underlying broke the prior-5-day-low invalidation.
- Days to best move, days to invalidation, close-after-5-days, close-after-10-days.
- Classification: `successful_continuation`, `partial_success`, `failed_breakout`, `stopped_or_invalidated`, or `no_follow_through`.
- Post-trade review note: what the setup got right/wrong and whether rule changes are needed.

This review is an accountability/learning gate for the recommendation engine. It does not require knowing the user's actual fill price or option spread P/L.

---

## Human approval checkpoint

When Task 5 completes:

- If OOS survives: report strategy evidence and ask the user whether to mark `liquid_pullback_continuation` as `approved` for paper-trade recommendations.
- If OOS fails: keep it `research_only` and propose the next deterministic variant.

Approval wording must be explicit:

> Approve `liquid_pullback_continuation` for paper-trade recommendation generation only. This does not authorize live trading or order execution.

---

## Expected first recommendation output shape

Once the strategy is approved and review gates pass, Wolfy should produce tables like:

| Ticker | Setup/Thesis | Catalyst/Evidence | Entry/Trigger | Stop/Invalidation | Target/Exit | Risk Notes | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| MSFT | EOD pullback continuation | FACT: close near rising fast MA, liquidity passed, approved signal row; JUDGMENT: trend pullback offers defined risk | Next session only above trigger | ATR/support stop | 2R/trailing exit | $5k paper risk, max 3 positions, no earnings landmine | pending Sentinel/Yang / paper_candidate |

---

## Verification command bundle

Run after implementation slices:

```bash
cd /root/.hermes/wolfy
python3 -m py_compile eod_signals.py eod_backtest.py visible_progress_ledger.py
python3 -m pytest test_eod_signals.py test_eod_backtest.py test_visible_progress_ledger.py -q
python3 visible_progress_ledger.py --format markdown
psql -d wolfy -X -A -F $'\t' -c "select name,status,latest_oos_sharpe,latest_oos_verdict,last_validated from strategies order by name;"
psql -d wolfy -X -A -F $'\t' -c "select s.dt, st.name, st.status, count(*) from signals s join strategies st on st.id=s.strategy_id group by 1,2,3 order by 1 desc,2 limit 20;"
```

---

## Rollback plan

- Revert code changes in modified Python/tests.
- Leave historical `signals` and `backtests` rows as audit artifacts unless a fixture accidentally wrote synthetic `ZZ%` rows; cleanup synthetic rows only.
- Set `strategies.status='research_only'` for `liquid_pullback_continuation` if a promotion was accidental.
- Do not delete real market-data rows.
