# Wolfy Signal and Market-Data Provenance Audit

Use when the user asks what Wolfy's signals are, whether volume is used, or where a feature originates.

## Evidence-first audit

1. Inspect the current strategy implementation, not just strategy names or notes.
2. Query Postgres `strategies` for status, params, validation verdict, and governance state.
3. Enumerate exact hard gates separately from advisory metadata and downstream risk warnings.
4. Trace each feature end-to-end:
   `vendor response field -> parser -> prices column -> feature formula -> strategy threshold`.
5. Query recent production rows and ingest-run provenance to verify the configured source is actually being used.
6. Exclude synthetic fixture dates/tickers/sources when presenting current signals (`ZZ*`, far-future dates, `unit-*`, `fixture`, `pytest`) unless explicitly auditing tests.
7. Clearly distinguish:
   - approved and recommendation-eligible;
   - approved in schema but not trustworthy due to failed/missing validation;
   - research-only/watch-only.
8. Never treat the latest signal date as production evidence until fixture contamination has been ruled out.

## Current implementation checkpoints

- Canonical implementation: `/root/.hermes/wolfy/eod_signals.py`.
- Price/feature lineage: `/root/.hermes/wolfy/eod_price_features.py`.
- Production EOD source is configured by `orchestration_config.DEFAULT_EOD_SOURCE` and cron wrappers.
- Massive adjusted aggregate mapping: `t,o,h,l,c,v -> dt,open,high,low,close,volume`.
- `vol_ratio = current daily volume / trailing-volume-window average`; inspect `DEFAULT_VOLUME_WINDOW` rather than assuming its value.
- `prices` currently has no per-row source field. Vendor provenance is recorded in `runs.source`/`runs.detail`; state this limitation instead of claiming row-level proof.
- EODHD/EODHS and Yahoo may exist as fallback/smoke sources; distinguish configured primary from supported alternatives.
- Robinhood is read-only broker enrichment and is not the canonical deterministic history or signal source.

## Report shape

Start with the direct answer, then a compact table:

`Strategy | Governance status | Exact inputs/gates | Volume role | Recommendation eligibility`

For provenance:

`Vendor | Endpoint/field | Stored column | Derived feature | Strategy use`

Conclude with the operational implication: whether a fresh qualifying approved signal exists, and whether `NO SETUP` is the correct outcome. Avoid presenting research-only signals as recommendations.
