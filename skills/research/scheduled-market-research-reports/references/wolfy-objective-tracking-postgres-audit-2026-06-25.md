# Wolfy objective/tracking Postgres audit pattern — 2026-06-25

Use when the user asks to check whether the Wolfy system is tracking to its goals, asks for the objective/status/next steps, or wants to view the Postgres data directly.

## Objective summary to anchor answers

Wolfy is intended to be an EOD-only, Postgres-primary stock research and paper-trading decision-support system:

- U.S./Robinhood-tradable stocks and ETFs first.
- Long-only; no shorts; options allowed only as human-approved, defined-risk paper structures.
- $5,000 paper account, max 3 concurrent positions, stops/invalidation required, avoid PDT issues.
- Closing-data decisions only; no broker authority, no live order placement, no money movement.
- Deterministic scripts compute prices, features, strategy signals, risk gates, and setup eligibility.
- LLMs interpret, rank, challenge, and explain; they do not invent signal values or numeric edge.
- Strategies must move `research_only -> candidate -> approved`; only the user can approve.
- Quiet/no-setup days are valid.

## Current audit query pattern

Prefer direct Postgres facts over memory. The active database is `wolfy`; local root can connect with:

```bash
psql -d wolfy
```

Useful fact queries:

```sql
select min(dt) first_price, max(dt) last_price, count(*) price_rows, count(distinct ticker) tickers from prices;
select min(dt) first_feature, max(dt) last_feature, count(*) feature_rows, count(distinct ticker) tickers from features;
select min(dt) first_signal, max(dt) last_signal, count(*) signal_rows, count(distinct ticker) tickers, count(distinct strategy_id) strategies from signals;
select s.id, s.name, s.status, s.latest_oos_sharpe, s.latest_oos_verdict, s.last_validated,
       count(sig.*) signal_rows, max(sig.dt) latest_signal
from strategies s
left join signals sig on sig.strategy_id=s.id
group by s.id
order by s.id;
select status, count(*) from setups group by status order by status;
select status, count(*) from recommendations group by status order by status;
select status, count(*) from paper_trades group by status order by status;
select count(*) reviews, max(created_at) latest_review from recommendation_reviews;
select decision, count(*) from recommendation_reviews group by decision order by decision;
select count(*) alpha_reports, max(created_at) latest_alpha_report from alpha_search_reports;
select status, count(*) from alpha_leads group by status order by status;
select count(*) chunks, count(embedding) embedded_chunks from knowledge_chunks;
```

Schema pitfall: the current EOD tables use `dt` for dates in `prices`, `features`, and `signals`, not `date`. If a visibility script reports `None`/unavailable while direct queries show data, suspect schema drift in the visibility layer before claiming the system lacks data.

## How to answer the status question

Use this structure:

1. `Objective` — concise restatement of the operating constitution.
2. `Tracking well` — durable facts from Postgres/cron, preferably in a table.
3. `Not there yet` — explicit blockers; do not soften them.
4. `Needed next` — ordered build/gate sequence.

Important wording:

- If every strategy is `research_only`, say no strategy is approved and Wolfy cannot present capital-ready setups yet.
- If `setups` is empty, say deterministic signals exist but setup generation is not active or is blocked by the approved-strategy gate.
- If `paper_trades` is empty, say the paper portfolio loop has not started.
- If Sentinel's latest review is older than a pending recommendation, call out the stale review handoff.
- Treat Alpha Search as lead generation only; a model timeout there does not invalidate script-only EOD ingest/signals.

## Browser/GUI access pattern

Do not expose Postgres directly to the public internet. Recommend:

```bash
ssh -L 5432:127.0.0.1:5432 root@SERVER_IP
```

Then connect a local GUI such as DBeaver/TablePlus/pgAdmin to host `127.0.0.1`, port `5432`, database `wolfy`, user `root` (or a least-privilege read-only role if created later).
