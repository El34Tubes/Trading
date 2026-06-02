# Wolfy report tables and scanner scale-up pattern — 2026-06-01

Session learning from the Wolfy implementation push:

## User-facing report format

The user explicitly asked to put reports in tabular format where it makes sense. For Wolfy-style recurring market research, update scheduled prompts and report templates so row/column facts are tables and narrative is short below each table.

Useful table targets:

- Scanner/lead rankings.
- Pending recommendations.
- Risk controls and account constraints.
- Sentinel review decisions.
- Yang technical entry/exit levels.
- Clerky/Kanban/job/DB status snapshots.

Recommended trade-candidate columns:

`Ticker | Setup/Thesis | Catalyst/Evidence | Entry/Trigger | Stop/Invalidation | Target/Exit | Risk Notes | Status`

Reviewer/technical variants:

- Sentinel: `ID | Ticker | Decision | Required Modification | Max Risk | Key Risk Flags | Reason`
- Yang: `ID | Ticker | Technical Status | Entry/Trigger | Stop | Target/Exit | R Multiple | Note`

Avoid turning every paragraph into a table. Use tables where comparison, status, ranking, or level data is clearer; keep narrative concise.

## Scanner scale-up implementation pattern

When the user asks how to get more leads into Wolfy sooner, do not just increase LLM cadence. Improve the deterministic scanner and handoff pipeline first:

1. Run a scanner freshness gate before decision reports. If market data is stale, block actionable recommendations and mark the report no-trade/watch-only.
2. Expand the liquid U.S. universe cache beyond a tiny curated list: S&P 500, Nasdaq 100, major ETFs, and liquid mid-cap names; keep low-liquidity/pump-prone names filtered unless explicitly requested.
3. Add deterministic factors before asking the LLM to reason: volume surge, 20-day breakout, relative strength vs SPY/QQQ/sector, ATR/risk compression, volatility squeeze, extension penalty, and liquidity filters.
4. Schedule lightweight intraday snapshots as script-only/no-agent jobs during market hours; preserve tokens and only alert on failures or material changes.
5. Auto-generate structured alpha-lead handoffs from top scanner anomalies. Treat these as leads, not recommendations.
6. Promote only complete tickets through the gated chain: scanner result → alpha lead → promotion gate → pending review → Sentinel → Yang/paper ledger → outcome grading.

This keeps the system fast without becoming a pump-chasing bot or creating recommendations from stale/noisy data.

## Verification pattern used

For Wolfy implementation changes, verify with the Postgres guard plus full test suite before accepting Kanban cards:

```bash
python /root/.hermes/wolfy/check_postgres_requirements.py
python -m pytest -q /root/.hermes/wolfy
```

On this session the suite returned `40 passed`, and the scanner freshness gate was accepted after confirming fresh scanner runs and action-gate output.
