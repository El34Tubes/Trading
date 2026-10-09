# Wolfy runs.ended_at alias + Massive shard smoke pattern (2026-07-21)

## Trigger

Mike ops saw two separate but related EOD operations issues:

1. An ad-hoc/LLM ops probe queried `runs.ended_at`, but Wolfy's canonical EOD `runs` ledger used `started` / `finished` plus existing compatibility aliases `started_at` / `completed_at`.
2. Default-profile EOD Massive ingest shards 2-5 showed historical cron failures after market close with same-calendar-day `/v2/aggs/.../<today>/<today>` 403 `NOT_AUTHORIZED` on the delayed/free data plan.

## Durable repair pattern

### 1. Add a nullable non-destructive `runs.ended_at` alias

Do not rename canonical columns or rewrite writers. Add a compatibility mirror:

```sql
ALTER TABLE runs ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ;
UPDATE runs
SET ended_at = COALESCE(ended_at, completed_at, finished)
WHERE ended_at IS NULL;
```

Then refresh the run alias trigger so future rows mirror `ended_at` from `completed_at` / `finished`, and expose it through `eod_feature_runs`.

Preserve the repair in both:

- `/root/.hermes/wolfy/postgres_init.sql`
- canonical `/root/.hermes/scripts/mike_safe_autorepair.py`

Then run canonical autorepair so it syncs Wolfy/profile copies:

```bash
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py  # second run should be silent
```

### 2. Treat Massive same-day shard failures as delayed-plan access unless proven otherwise

If cron `Last run` still shows a 403 from `/v2/aggs/ticker/<T>/range/1/day/<today>/<today>`, first check whether the code already defaults Massive EOD end date to the previous business day. Historical cron errors can remain visible until the next scheduled shard window even after the fix is in place.

Manual verification is stronger than the stale `Last run` text:

```bash
cd /root/.hermes
for n in 2 3 4 5; do
  python3 /root/.hermes/scripts/wolfy_eod_after_close_ingest_shard_${n}.py >/tmp/wolfy_shard_${n}.json || exit $?
  python3 - <<'PY'
import json, os
p = os.environ['P']
d = json.load(open(p))
print({
  'bars_fetched': d.get('bars_fetched'),
  'feature_run_id': d.get('feature_run_id'),
  'skipped': sum(1 for x in d.get('fetch_plan', []) if x.get('skipped')),
  'latest': sorted({x['latest_dt'] for x in d.get('latest', [])}),
})
PY
done
```

A healthy smoke may report `bars_fetched: 0`, all tickers `skipped: already_current`, and latest dates equal to the previous business day. That is healthy for a delayed/free Massive plan; it proves the shard avoids same-day 403s and can recompute feature rows.

For no-write API proof, use the dry-run runner against one ticker and confirm latest date is previous business day:

```bash
cd /root/.hermes
python3 - <<'PY'
import sys
sys.path.insert(0, '/root/.hermes/wolfy')
from orchestration_runner import run_eod_ingest
raise SystemExit(run_eod_ingest(tickers=['SPY'], dry_run=True, days=5, source='massive'))
PY
```

## Verification checklist

- `psql -v ON_ERROR_STOP=1 -d wolfy -f /root/.hermes/wolfy/postgres_init.sql`
- `select id, job, status, rows_written, started_at, ended_at from runs where job like 'eod%' or job like 'feature%' order by started_at desc limit 5;`
- `select count(*) as missing_ended_at from runs where (job like 'eod%' or job like 'feature%') and ended_at is null and finished is not null;` should be 0.
- `python3 -m py_compile` for canonical/profile autorepair copies.
- Targeted EOD tests, e.g. `cd /root/.hermes/wolfy && python3 -m pytest test_eod_price_features.py -q`.
- Run canonical autorepair twice; second run should be silent.
- Re-check `hermes --profile default cron list --all`; historical `Last run` errors may remain until the next real scheduled shard run.

## Reporting nuance

Do not report the historical cron 403 text as an active blocker after manual shard smokes prove previous-business-day behavior. Report it as stale cron status that should clear on the next scheduled shard window. Also distinguish usage-volume threshold output from active limits: if the dedicated usage watchdog runs silently twice, do not pause jobs based on the aggregate token threshold alone.
