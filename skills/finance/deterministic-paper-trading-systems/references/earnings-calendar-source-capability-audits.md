# Earnings-calendar source capability audits

Use this pattern when a deterministic trading system has an earnings/event-risk gate but the calendar table is empty or its provider entitlement is uncertain.

## Read-only audit sequence

1. **Inventory the consuming contract first.** Identify the columns and semantics the signal/risk code expects (for example `ticker`, event date, BMO/AMC session, and confirmation state). Inspect the live table in a read-only transaction and count/date-bound its rows; do not infer ingestion merely because the schema exists.
2. **Separate transport support, endpoint existence, and entitlement.** A repository may have a generic authenticated HTTP helper without a domain client, and a provider may document an endpoint that the configured plan cannot access. Report these as three distinct findings.
3. **Use bounded entitlement probes.** Query one or two liquid U.S. symbols, a narrow recent/upcoming date range, and `limit=1` or `2`. Summarize HTTP status and non-secret error text only. Never print keys, complete authenticated URLs, environment files, or request headers.
4. **Probe plausible lookalikes.** Verify whether an included endpoint called “events” actually contains earnings. Provider ticker-event APIs may expose only symbol changes; splits/dividends are corporate actions but do not substitute for an earnings calendar.
5. **Inspect repository coverage.** Search for explicit earnings endpoint paths, normalizers, ingestion orchestration, tests, and schema ownership. A generic `get_json()` helper is transport reuse, not an implemented earnings client.
6. **Audit provenance fitness before recommending ingestion.** A durable earnings feed should preserve at least:
   - provider/source and provider event ID;
   - event date and explicit or deterministically derived session;
   - projected/confirmed/postponed/canceled status where supplied;
   - provider update timestamp as `available_at` when its semantics support that mapping;
   - local `observed_at` and committed `ingested_at`;
   - raw payload or immutable hash/version sufficient to retain revisions.
7. **Compare alternatives on source-relevant facts.** Use current first-party plan/docs evidence for entitlement, price, recency, history, U.S. coverage, confirmation, session timing, revision timestamps, source URLs, limits, and legal/retention fitness. Distinguish a cheap technically accessible feed from one that satisfies point-in-time provenance.
8. **End with a no-write proof.** Report the read-only transaction/rollback, unchanged git status relative to the starting state, and any pre-existing dirty/untracked files without touching them.

## Massive/Polygon endpoint distinctions observed in 2026

Treat these as a re-verification checklist, not permanent plan facts:

- `GET /benzinga/v1/earnings` is the direct earnings-calendar dataset. Its documented fields include ticker, event date, scheduled time, projected/confirmed date status, provider record ID, and `last_updated`; it supports recent and upcoming date filters. It is a separately entitled Benzinga partner dataset, not automatically included with a Stocks plan.
- `GET /tmx/v1/corporate-events` includes earnings announcement/call/result event types, event status, a TMX record ID, and sometimes a primary-source URL. It is a separately entitled TMX partner dataset. Session may be encoded in an event name rather than a dedicated field, and a provider revision timestamp was not documented in the audited schema.
- `GET /vX/reference/tickers/{id}/events` is not a general earnings calendar: the documented/smoked event type was `ticker_change` only.
- Standard splits and dividends endpoints are useful for price-quality audits but are not substitutes for earnings dates.

On a bounded Wolfy probe dated 2026-08-29, the configured Massive credential authenticated to included stock reference/ticker-event data but returned HTTP 403 “not entitled” for both Benzinga Earnings and TMX Corporate Events. This proves endpoint-specific entitlement absence for that credential at that time; it does not prove the key was invalid or that those products remain unavailable later. Re-probe before acting.

## Existing alternate-feed lesson

A configured provider key and an existing price-bar client do not imply calendar entitlement. In the same audit, a bounded EODHD earnings-calendar request authenticated but returned a free-plan restriction, while its ordinary EOD data remained available. Preserve this distinction and compare the provider's current standalone calendar product or broader paid plan before proposing implementation.

## Schema pitfall

A minimal table such as `(ticker, event_dt, session, confirmed)` can support a current-state event gate but cannot prove point-in-time correctness or reconstruct date revisions. Do not silently map a revision-capable provider into that table and discard provider ID/update timestamps. Add an append-only observation/revision surface or an equivalent raw provenance ledger before calling the ingestion auditable.

## Reporting template

State the verdict first, then provide:

1. configured-plan endpoint matrix (`endpoint`, `probe scope`, `HTTP/result`, `usable now`);
2. repository client coverage versus missing domain logic;
3. live table row count and provenance gaps;
4. 2–3 current alternatives with exact coverage/cost/field tradeoffs;
5. a recommendation keyed to deterministic session, confirmation, and point-in-time needs;
6. explicit confirmation that no credentials, files, or database rows were exposed or modified.
