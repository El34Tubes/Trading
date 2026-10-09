# Wolfy RS breakout validation and tight-risk revision — 2026-07-30

## Context

User approved exhausting the current options-focused RS breakout setup before switching to a different technical strategy, and clarified that success should be evaluated on the underlying stock/ETF setup, not on the user's option fill/P&L.

Parent strategy:

- `liquid_rs_breakout_continuation`
- 5-day high breakout
- 20-day RS vs SPY
- `vol_ratio >= 1.2`
- close within 5% of recent high
- stop below prior 5-day low
- 10-trading-day max hold
- partial at 1.5R, trail remainder
- 2–3 week slightly OTM call-spread expression
- options liquidity informational/user-evaluated only

## Durable implementation lessons

### 1. Grade underlying setup accuracy, not option P/L

Wolfy may not know if/when the user entered or what option spread/fill they used. Add/keep a deterministic setup-outcome evaluator that measures the underlying after signal date:

- target price = entry + 1.5R, where R = entry - stop
- horizon = max 10 trading days
- conservative same-bar assumption: stop before target if both print
- output fields: `classification`, `hit_target`, `hit_stop`, `mfe_r`, `mae_r`, `mfe_pct`, `mae_pct`, `days_to_best_move`, `exit_reason`

Classifications used:

- `successful_continuation`
- `partial_success`
- `no_follow_through`
- `failed_breakout`
- `stopped_or_invalidated`

### 2. Validate broad setup, then mine successful cohorts

Initial validation of broad `liquid_rs_breakout_continuation` over 2024-08-01..2026-07-29:

- generated about 12.3k historical research signals
- next-close OOS Sharpe: ~0.65, below user gate of 0.75
- formal verdict: failed; stay `research_only`
- setup-outcome baseline: ~10.6% hit 1.5R over ~12.3k outcomes

Do **not** force recommendations from this broad version.

Backward setup-success cohort mining found a much stronger profile:

- stop risk <= 4%
- RS excess vs SPY >= 2%
- `vol_ratio >= 2.0`
- about 57–58 signals
- about 39–40% hit 1.5R
- stop rate about 31%
- median MFE around 1.0R

This became the research-only revision:

- `liquid_rs_breakout_tight_risk_volume`

### 3. Keep small-sample variants research-only until robust validation

The tight variant showed promising setup-success stats and next-close OOS Sharpe around 2.06 in one run, but sample splitting was insufficient because all trades fell into the default OOS window / too few independent IS trades. Keep it `research_only` until a frequency-aware validation method confirms it.

Recommended next validation work:

1. frequency-aware split for sparse strategies, not fixed 63-day OOS only;
2. compare 1.0R / 1.5R / 2.0R targets;
3. compare stop rules: prior 5-day low, ATR stop, close back below breakout trigger;
4. test SPY > 50-day / SPY > 20-day regime filters;
5. evaluate top-N-per-day concentration separately from broad all-signal stats;
6. require explicit human strategy approval before recommendations/paper logging.

### 4. Postgres fixture pitfall

Tests that use the shared Wolfy Postgres DB must not erase live benchmark rows. A prior cleanup helper used `SPY` as a synthetic fixture ticker and deleted real SPY prices/features, breaking RS-vs-SPY generation. For future tests:

- use synthetic `ZZ...` tickers and far-future dates such as `2099-*`;
- if a live benchmark like `SPY` must be used in tests, cleanup only the far-future fixture rows (`dt >= DATE '2099-01-01'`), never all `SPY` rows;
- before validating RS strategies, verify SPY benchmark history exists and ingest it via the normal EOD wrapper if missing.

### 5. Reporting shape

When user asks “how are we doing?” after this kind of run, answer in gate language:

- broad setup failed and remains `research_only`;
- tight-risk/high-volume variant looks promising but is still `research_only`;
- no actionable recommendations yet;
- next work is robust validation of the tight variant or trying the next technical setup class.
