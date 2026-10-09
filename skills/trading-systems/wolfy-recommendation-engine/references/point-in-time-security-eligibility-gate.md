# Point-in-Time Security Identity and Eligibility Gate

Use this reference when implementing or auditing Wolfy's versioned U.S./liquidity/security-risk gate before strategy evaluation.

## Required audit sequence

1. Read the accepted task specification before inferring scope from old universe code.
2. Inspect both repository schema definitions and the live read-only Postgres catalog; mature databases may contain compatibility columns absent from one bootstrap path.
3. Trace every universe producer and consumer, not only the nominal selector:
   - provider reference fetch/normalization;
   - `universe_symbols` and compatibility views;
   - tier/backfill selection;
   - membership snapshots;
   - recommendation-universe queries;
   - price/feature liquidity computation.
4. Read the provider's current official reference endpoint and type-code documentation. If credentials already exist, a read-only type-list probe is useful because exact codes are safer than ticker/name heuristics.
5. Finish with a narrow TDD decomposition, migration hazards, and a read-only workspace status check.

## Current Wolfy pitfalls discovered

- A mutable one-row-per-symbol table cannot represent point-in-time identity, ticker reuse, delisting, or effective-date changes.
- `last_seen` is ingestion time, not source `available_at`; a concatenated `source` string is not provenance.
- Fetching only `active=true` records means inactive/delisted transitions cannot be learned, and absence from a partial page must never deactivate a symbol.
- OR-merging `is_etf` makes classification irreversible and can contaminate reused symbols.
- Ticker suffix and name regexes are unsafe as the identity authority. Exact provider security type, locale, market, exchange, and currency should lead; regexes may remain secondary warnings.
- Generic ETF type is insufficient to identify leveraged/inverse products. Use a versioned explicit allowlist for accepted unlevered broad/sector ETFs, with single-stock ETFs rejected.
- Existing tier liquidity thresholds may be declarative only. Verify they are actually consumed.
- Wolfy's historical `features.dollar_vol` may be one-session `close * volume`; do not call it 20-session average dollar volume without tracing the formula.
- A current membership snapshot copied from `active/enabled` is not a point-in-time eligibility record unless it carries policy version, identity observation, source availability cutoff, reasons, and immutable provenance.
- Unknown or conflicting identity must fail closed; user denylist precedence is absolute.

## Provider observation contract

Persist source observations append-only with, at minimum:

- symbol and stable identifiers when available (for example FIGIs/CIK);
- exact security type, locale, market, primary exchange, and currency;
- active/delisted state;
- effective date or range;
- `available_at` and ingestion timestamp;
- source endpoint, query/as-of date, request identifier, and provider update timestamp;
- raw payload or deterministic source fingerprint.

A record fetched today for an old effective date was not necessarily knowable then. Unless the source provides a trustworthy publication timestamp, use receipt time as `available_at`; never backdate knowledge to the effective date.

## Deterministic eligibility result

Return a typed result containing policy version, decision date/timestamp, pass/fail, canonical reasons, identity-observation provenance, and liquidity facts. Canonical failures should distinguish at least:

- missing/ambiguous/conflicting identity;
- observation unavailable at decision time;
- foreign locale or non-USD currency;
- OTC/unsupported exchange or market;
- unsupported security type;
- unapproved, leveraged/inverse, or single-stock ETF;
- inactive/delisted symbol;
- user denylist;
- minimum price failure;
- insufficient 20-session average dollar volume or incomplete liquidity window.

## Safe migration pattern

- Add append-oriented identity observations and versioned policy/allowlist/denylist relations; do not overload mutable `universe_symbols` as history.
- Use explicit `ALTER TABLE`, constraints, and indexes for populated upgrades; `CREATE TABLE IF NOT EXISTS` alone does not upgrade existing relations.
- Preserve compatibility views and account for dependencies when dropping/recreating them.
- Test clean bootstrap, populated partial-schema upgrade, rerun idempotency, direct SQL constraint bypasses, effective-date overlaps, and late-arriving observations.
- Backfill in shadow mode first. Compare old and new classifications and do not silently rewrite current `active`/`is_etf` state.
- Keep policy construction separate from downstream broad-universe integration. The security gate should exist and be testable before recommendation selection begins consuming it.

## Focused RED matrix

Cover: U.S. common stock, approved ETF, foreign locale, OTC, non-USD, warrant/unit/right/preferred/ADR, leveraged/inverse ETF, single-stock ETF, inactive/delisted symbol, missing identity, conflicting overlap, late-arriving historical observation, effective-date change, incomplete 20-session liquidity, minimum-price failure, and denylist-always-wins behavior.
