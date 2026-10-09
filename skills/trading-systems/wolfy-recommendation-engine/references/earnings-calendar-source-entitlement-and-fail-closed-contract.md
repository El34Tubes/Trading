# Earnings Calendar Source Entitlement and Fail-Closed Contract

## Capability probe pattern

Before implementing an earnings calendar against an existing market-data key:

1. Probe one upcoming and one recent symbol/date request.
2. Record endpoint, HTTP status, entitlement class, useful fields, update cadence, and history depth without printing credentials or raw auth headers.
3. Probe any generic ticker-events endpoint separately; ticker changes are not an earnings calendar.
4. Query the live earnings schema read-only and compare it with the required provenance/revision contract.
5. Re-probe before purchase or implementation because provider pricing and entitlements change.

## Wolfy observations on 2026-08-29

- Massive `/benzinga/v1/earnings`: HTTP 403, current key not entitled.
- Massive `/tmx/v1/corporate-events`: HTTP 403, current key not entitled.
- Massive ticker-events endpoint: HTTP 200 but returned ticker-change events, not earnings.
- Existing EODHD `/api/calendar/earnings`: HTTP 403 under the configured entitlement.
- Production `earnings_calendar` had zero rows and only `ticker`, `event_dt`, `session`, `confirmed`; it could not preserve source, observation/availability/ingestion timestamps, provider event identity, raw fingerprint, or revision history.

Observed public pricing at that time: Massive Benzinga Earnings and TMX partner datasets were listed at $99/month each; EODHD's calendar offering was listed lower-cost but with weaker confirmation/revision provenance. Treat all prices as stale until rechecked.

## Recommendation logic

- Preferred fit when purchased: Massive Benzinga Earnings because `ticker`, `date`, `time`, `date_status`, `last_updated`, and `benzinga_id` map cleanly to date/session/confirmation/revision fields.
- TMX is an alternative when primary-source URLs and broad corporate-event coverage matter more than direct session/revision fields.
- EODHD is a lower-cost alternative but requires Wolfy-owned observation/revision tracking and has weaker documented provenance.
- A paid purchase remains a human decision; provider research does not authorize spending.

## Immediate behavior without a source

Do not fabricate rows and do not treat no row as no event. Implement and test `earnings_unknown` as a fail-closed event-risk state for uncovered tickers. Keep PEAD research-only. A current calendar can support a forward event veto, but historical PEAD requires point-in-time actuals, estimates, publication timestamps, revisions, and `available_at <= decision_timestamp` joins.

Prefer append-only event observations or a separate revision table over overwriting a four-column current-state table. Preserve raw/fingerprint provenance and every observed revision.
