# Wolfy alpha modules, Yang agent, Kanban allocator, and Postgres helper fix — 2026-05-31

## When this applies

Use this reference when extending the user's Wolfy/Jonah/Sentinel research desk with new alpha modules, agent roles, Kanban cards, scheduled work allocation, or Postgres coordination helpers.

## User preference signals

- The user wants new Wolfy capabilities broken into Kanban cards, not just implemented ad hoc.
- The user wants scheduled work allocation so cards are picked off over time, but bounded to avoid uncontrolled spawning/token use.
- The user is comfortable adding specialist agents when roles are clearly separated.
- For trade recommendations, the desired authority chain is: Wolfy finds alpha -> Sentinel challenges/approves -> Yang handles technical entry/exit.

## YouTube/transcript ingestion lesson

If a YouTube transcript fetch is blocked by YouTube bot/sign-in controls, do not claim exact transcript ingestion. Save only provisional knowledge based on user-stated sections, create a Kanban card to obtain the exact transcript/timestamps, and explicitly tell the user what was and was not ingested.

For finance videos, extract requested concepts into durable Wolfy notes/rules only when source text or user-provided section names support them. Mark provisional notes as needing transcript verification.

## Alpha modules added in this session

Concepts the user requested for Wolfy:

- Insider buying module: insider open-market purchases are thesis support, not a standalone trigger; check role, materiality, cluster buying, liquidity, 10b5-1 context, dilution/offering risk, and pump/manipulation risk.
- Separate alpha-search report: lead generation only, distinct from the twice-daily Wolfy trade recommendation report.
- Financial Twitter/X scanner: useful as noisy lead generation but requires source credibility, bot/promotion checks, liquidity checks, and suspicious-activity filters. If official X tooling/API is not configured, evaluate free alternatives such as SEC filings, Stocktwits/public chatter, Reddit, news search, and price/volume anomaly scans rather than blocking.
- Suspicious-activity layer: flag low-float spikes, reverse splits, dilution/offering risk, abnormal volume without catalyst, influencer/cashtag pile-ons, offshore/opaque risk, and pump-like setups.

## Yang agent pattern

Create Yang as a separate Hermes profile when the user wants a specialist technical-analysis agent. Yang's scope:

- Technical entry/exit only after Wolfy alpha and Sentinel review.
- Does not originate alpha theses.
- Does not approve trades.
- Produces entry trigger/zone, stop/invalidation, target/exit plan, ATR/R multiple, volume/trend/relative-strength read, and status: actionable-now / wait-for-trigger / watch-only / no-trade.

In this session Yang used:

- Profile: `yang`
- Context script: `/root/.hermes/wolfy/yang_technical_context.py`
- Cron wrapper: `/root/.hermes/scripts/wolfy_yang_technical_context.py`
- Cron job: `de6f05f10cb5`, after Sentinel.

## Kanban allocator pattern

When scheduling a recurring allocator, prefer a script-only `no_agent=true` cron job that runs a bounded dispatcher pass. Add safety checks:

- Do not dispatch if tasks are already running.
- Do not dispatch if the number of ready tasks exceeds a small safe cap; report/hold for manual review instead.
- Assign agent-specific cards to matching profiles when available, e.g. Yang cards to `yang`.

Avoid using a raw dispatcher in cron without caps because it may spawn every ready card for a profile in one pass.

## Postgres helper fix pattern

The Wolfy Postgres coordination helper had a psycopg/Postgres type inference bug in `block_task()`:

```sql
concat_ws(E'\n', description, %s)
```

Postgres could not determine the type of parameter `$1`. Fix by casting the placeholder:

```sql
concat_ws(E'\n', description, %s::text)
```

Add/keep smoke tests for:

- agent run insert and finish,
- task dedupe and claiming,
- block path updates status and appends reason.

After diagnostic context scripts claim a task/run during troubleshooting, close the rows via `wolfy_agent_cli.py block ...` or `complete ...` to avoid orphaned `in_progress` rows.

## Postgres helper integration follow-through

After the `block_task()` bug fix, wire agent contexts so the ledger is active, not passive:

- Wolfy report context: `/root/.hermes/wolfy/wolfy_report_context.py` with cron wrapper `/root/.hermes/scripts/wolfy_report_context.py`; starts `agent_runs` row for `agent_name='Wolfy'`, `role='analyst_recommender'`, `job_id='wolfy-twice-daily-report'`.
- Alpha Search context: `/root/.hermes/wolfy/alpha_search_context.py` with wrapper `/root/.hermes/scripts/wolfy_alpha_search_context.py`; starts `agent_runs` row for `agent_name='Wolfy'`, `role='alpha_scout'`, `job_id='wolfy-alpha-search-report'`.
- Yang context should also claim/start/finish Postgres rows, not just print SQLite/scanner context.
- Stale cleanup: `/root/.hermes/wolfy/cleanup_stale_agent_coordination.py` with wrapper `/root/.hermes/scripts/wolfy_cleanup_stale_agent_coordination.py`; scheduled as no-agent job `59a6c39f7b60`, marks `in_progress`/`started` rows older than 3 hours as blocked.
- Aggregate usage accounting: table `agent_usage_snapshots`, script `/root/.hermes/wolfy/capture_usage_snapshot.py`, wrapper `/root/.hermes/scripts/wolfy_capture_usage_snapshot.py`, cron job `32a8b909e38a`; parses `hermes insights --days 1` into Postgres until per-run token metadata is available.

Verification commands used:

```bash
cd /root/.hermes/wolfy
python3 -m pytest -q test_agent_coordination_smoke.py
python3 -m py_compile wolfy_report_context.py alpha_search_context.py yang_technical_context.py cleanup_stale_agent_coordination.py capture_usage_snapshot.py wolfy_agent_coordination.py wolfy_agent_cli.py
psql -d wolfy -c "SELECT agent_name, status, count(*) FROM agent_runs GROUP BY agent_name,status ORDER BY agent_name,status; SELECT count(*) FROM agent_usage_snapshots;"
```
