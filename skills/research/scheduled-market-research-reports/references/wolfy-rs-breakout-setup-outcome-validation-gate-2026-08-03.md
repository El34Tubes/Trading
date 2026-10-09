# Wolfy RS breakout setup-outcome validation gate — 2026-08-03

## Context

The user approved exhausting the RS-breakout recommendation strategy before moving to other technical setups. The earlier broad `liquid_rs_breakout_continuation` failed formal OOS gates, and a tighter small-sample variant was not enough. The key correction was that options-timed recommendations should be validated by the underlying setup outcome — whether the stock/ETF continued higher and hit deterministic R targets before invalidation — not by the user's eventual option fill/P&L or by simplistic next-close returns.

## Durable technique

Add a setup-outcome-native gate for options-timed technical strategies:

- deterministic entry from the signal row,
- deterministic stop/invalidation,
- target R multiple,
- max holding horizon,
- hit target before invalidation,
- MFE/MAE in R terms,
- frequency-aware chronological OOS tail,
- auditable threshold/failure-reason payload.

Useful thresholds from this session:

```text
min_sample = 100
min_oos_sample = 25
min_hit_rate = 0.55
min_oos_hit_rate = 0.50
max_stop_rate = 0.45
min_median_mfe_R = 1.0
oos_fraction = 0.25
```

## Resulting variant

Selected candidate strategy:

```text
liquid_rs_breakout_close_confirm_1r
```

Rules:

- 5-day high breakout,
- SPY above 50-day SMA,
- 20-day RS excess vs SPY >= 2%,
- `vol_ratio >= 1.2`,
- prior-low risk <= 5%,
- invalidation on close back below breakout level,
- target 1R,
- max hold 10 trading days,
- 2–3 week slightly OTM call-spread expression preferred,
- options liquidity informational/user-reviewed only.

Live validation report/backtest row:

```text
backtest_id = 106
sample = 1085
OOS sample = 272
hit_rate = 63.13%
OOS hit_rate = 68.75%
stop_rate = 35.94%
median_mfe_R = 1.8539
status_after_validation = candidate
```

Important: `candidate` is still not `approved`; no recommendations or paper trades should be created until explicit human approval and the approved-gated writer/Sentinel/Yang/Postgres paper-ledger tasks are complete.

## Test/DB pitfall

Wolfy tests currently run against shared Postgres. Do not let test helpers reset real production strategy governance state. A helper that set RS breakout strategies back to `research_only` erased the candidate promotion after validation. Fix pattern:

- use synthetic `ZZ...` tickers and far-future fixture dates such as `2099-*`,
- cleanup only fixture rows,
- if a live benchmark ticker such as `SPY` is used, delete only far-future fixture rows and never real history,
- do not blanket-update `strategies.status`, `latest_oos_verdict`, or `last_validated` in test cleanup,
- tests that assert seeded defaults should allow real production statuses such as `candidate` while still verifying the strategy definition/params.

## Verification pattern

Run focused and full tests before committing:

```bash
cd /root/.hermes/wolfy
python3 -m pytest test_eod_backtest.py -q
python3 -m pytest -q
```

Session verification reached `123 passed`; commits included the setup-outcome gate and the test-governance preservation fix.
