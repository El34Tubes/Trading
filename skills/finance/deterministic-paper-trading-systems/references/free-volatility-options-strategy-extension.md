# Free volatility and market-structure extension pattern

Use this reference when extending a deterministic EOD strategy with free technical data and an options-oriented volatility branch.

## Source roles

Keep canonical OHLCV unchanged. Add orthogonal public observations in dedicated, provenance-aware tables:

- Cboe VIX history: market volatility context.
- Cboe aggregate put/call statistics: options sentiment context.
- FINRA daily short-sale volume: off-exchange transaction-flow research; never call it market-wide short interest.
- Nasdaq per-symbol short interest: semimonthly, lagged classification context; not an entry trigger.
- U.S. Treasury curve: risk-regime context.
- Locally derived breadth, sector-relative strength, realized volatility, contraction/expansion, close quality, and volume percentiles: deterministic signal inputs.

Every external observation should preserve:

- `observation_date` or settlement date;
- `available_at`/publication timestamp;
- source and source URL;
- ingestion timestamp;
- raw payload or source-run lineage.

Historical replays must filter on both observation date and availability. Never fetch a current webpage during a replay and label it as historical data.

## Options-volatility strategy pattern

Do not weaken an already approved strategy in place. Add a separate `research_only` strategy variant and require chronological validation before promotion.

A safe initial branch:

1. Retain baseline breakout, relative strength, volume, trend, underlying liquidity, bounded stop-distance, event, drift, concentration, and portfolio-risk gates.
2. Require prior volatility contraction followed by orderly range/volume expansion.
3. Require strong close location and reject disorderly gap/wick behavior.
4. Require supportive point-in-time breadth and stock-versus-sector plus sector-versus-SPY confirmation.
5. Treat high realized volatility and high VIX as context, not automatic rejection. Store the values explicitly; do not impose an arbitrary maximum merely because volatility is high.
6. Require `defined_risk_options_only`, an actual option instrument, acceptable option liquidity/spread, and no equity fallback.
7. Preserve paper-only/no-live-execution metadata.

Current option-chain snapshots cannot serve as historical IV/Greeks data. Missing history must remain missing rather than reconstructed from present snapshots.

## Point-in-time breadth and schema safeguards

Breadth must not be reconstructed using today's active universe:

1. Add a durable universe-membership snapshot/history table carrying date, symbol, eligibility, sector/classification provenance, source, and snapshot timestamp.
2. Snapshot the current universe before current-session breadth computation.
3. During historical computation, require an existing snapshot for that date. If absent, raise/skip explicitly and start forward collection; do not pretend current membership is point-in-time history.
4. Label the derived row with the exact universe definition/transformation version.
5. If a previously generated breadth row used current membership historically, remove only the proven generated artifact and leave all unrelated market data untouched.

Durable DDL should exist in both a new additive migration and the runtime schema guard. Keep old applied migrations unchanged. Canonical initialization SQL should also be aligned, but only after separating unrelated worktree edits. An idempotent migration smoke should use `psql -v ON_ERROR_STOP=1`; a lack of `CREATEDB` permission calls for non-destructive live-schema validation, not skipping migration verification.

## Free-source operational boundaries

- Cboe VIX history can support historical regime context, but store an explicit next-session-safe availability timestamp.
- A Cboe current daily put/call page is a current observation only unless an official dated archive is being parsed.
- FINRA daily files should be dated from the file itself and become available after publication; retain the facility-scope label.
- Nasdaq's free public endpoint is suitable for bounded, cached per-symbol forward collection, not a fabricated bulk-history backfill.
- Treasury observations also need publication-safe availability timestamps.
- Feed failure or schema drift must produce unavailable/stale context for the research strategy, never a default numeric zero.

## Testing and operational verification

- TDD parsers with compact representative fixtures.
- Test idempotent upserts and publication-lag/lookahead behavior.
- Test that high realized volatility can pass when structure is constructive.
- Test that high volatility alone cannot pass.
- Test that an options-only strategy rejects equity fallback.
- Run focused tests, full regression, compilation, diff checks, dry-run orchestration, and a transaction-rollback signal-generation smoke.
- Verify the committed artifact, not only a dirty working tree. For a clean archive test, create/extract the archive before invoking a command whose `workdir` points inside it; tool runtimes validate `workdir` before running the shell command.
- Keep unrelated dirty files unstaged and commit only scoped paths.

## Important interpretation notes

- Free does not mean unrestricted redistribution; retain licensing/terms notes.
- Cboe put/call page schemas can change; validate supported labels and freshness.
- FINRA short volume is transaction flow through FINRA reporting facilities, not outstanding short positions.
- Nasdaq short interest is lagged and slow-moving.
- Breadth backtests require point-in-time universe membership to avoid survivorship bias.
