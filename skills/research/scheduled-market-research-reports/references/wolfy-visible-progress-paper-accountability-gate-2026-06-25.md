# Wolfy visible progress paper/accountability gate — 2026-06-25

Session pattern for the daily Wolfy optimization planner when `paper-postgres` is important but true migration is too broad/risky for the daily throttle.

## Context

- Required preflight: snapshot time, git status, default/active Hermes cron jobs, active Hermes/Wolfy/Postgres processes, background sessions, and recent cron/agent failures before touching files.
- Observed conflict profile: frequent jobs due soon (Jonah, storage/usage/embedding, stale cleanup, safe autorepair, allocator), with market/report windows later. That made read-only helper work safe, but schema migration, cron edits, task mutation, and long backtests unsafe.
- EOD constitution still governs: no live trading, no auto-execution, no strategy approval, human approval required before actionability.

## Safe bounded optimization

Add/maintain a read-only paper/accountability section in `/root/.hermes/wolfy/visible_progress_ledger.py` by querying Postgres only:

- `paper_trades_total`
- `open_paper_trades`
- `open_paper_trades_without_stop`
- `closed_pnl_total`
- `latest_paper_trade_dt`
- `recommendations_total`
- `pending_recommendations`
- `pending_recommendations_without_stop`

Render both:

1. A compact Snapshot row: `paper_trades=<n> open=<n> open_without_stop=<n> pending_recs=<n> pending_recs_without_stop=<n>`.
2. A dedicated `## Paper/accountability gate` Markdown table with an explicit gate note: `paper/accountability only; no live trading or auto-execution`.

## Why this matters

This advances the `paper-postgres` TODO without mutating schema or consumers. It makes the live Postgres paper-ledger gap visible before attempting migration work, and gives future runs an evidence base for deciding the next bounded migration slice.

## Verification recipe

Use real outputs, but keep probes read-only and compact:

```bash
cd /root/.hermes/wolfy
python3 -m py_compile visible_progress_ledger.py
python3 visible_progress_ledger.py --json > /tmp/wolfy_visible_progress_ledger.json
python3 visible_progress_ledger.py --limit 2 > /tmp/wolfy_visible_progress_ledger.md
python3 - <<'PY'
import json
with open('/tmp/wolfy_visible_progress_ledger.json') as f:
    data = json.load(f)
print(data.get('postgres', {}).get('paper_ledger'))
PY
python3 - <<'PY'
import psycopg
conn = psycopg.connect('dbname=wolfy user=root host=/var/run/postgresql')
with conn, conn.cursor() as cur:
    cur.execute('select count(*) from paper_trades')
    print('paper_trades_total', cur.fetchone()[0])
    cur.execute('select status,count(*) from recommendations group by status order by status nulls last')
    print('recommendation_status_counts', cur.fetchall())
PY
```

Expected healthy shape: compile succeeds, JSON contains `postgres.paper_ledger`, Markdown contains `## Paper/accountability gate`, and direct Postgres counts agree with the ledger.

## Deferral rule

If true paper-ledger migration requires Postgres schema/database maintenance or multiple consumer edits, defer it from the daily optimizer unless the window is clearly idle and the scope stays within throttle. Run `/root/.hermes/wolfy/check_postgres_requirements.py` before any Postgres schema/package maintenance.
