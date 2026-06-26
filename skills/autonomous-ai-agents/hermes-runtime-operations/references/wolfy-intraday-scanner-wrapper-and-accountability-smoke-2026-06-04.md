# Wolfy intraday scanner wrapper sync + accountability smoke fixture seeding (2026-06-04)

## Trigger
Mike ops run saw stale recent-error tails around:
- missing `/root/.hermes/wolfy/wolfy_intraday_scanner_snapshot.py` when cron used global wrapper name `wolfy_intraday_scanner_snapshot.py` but live implementation was `intraday_scanner_snapshot.py`.
- `accountability_loop_smoke.py --db /tmp/new.db ...` failing on a brand-new fixture DB with `sqlite3.OperationalError: no such table: alpha_leads` even though pytest passed using prebuilt fixtures.

## Durable fix pattern

### 1. For renamed no-agent cron helpers, preserve all invocation layers
When a cron-facing Wolfy helper is renamed or introduced, check/sync:

```text
/root/.hermes/wolfy/<legacy_or_cron_name>.py
/root/.hermes/scripts/<legacy_or_cron_name>.py
/root/.hermes/profiles/mike/scripts/<legacy_or_cron_name>.py
/root/.hermes/profiles/clerky/scripts/<legacy_or_cron_name>.py
```

For `wolfy_intraday_scanner_snapshot.py`, the durable wrapper delegates to live implementation `/root/.hermes/wolfy/intraday_scanner_snapshot.py` and imports `main()` with `/root/.hermes/wolfy` on `sys.path`.

Teach `/root/.hermes/scripts/mike_safe_autorepair.py` to:
- include the wrapper in `MIKE_SCRIPTS` and `CLERKY_SCRIPTS`.
- preserve a global wrapper in `LEGACY_WRAPPERS`.
- preserve a Wolfy-local compatibility wrapper in `LEGACY_WOLFY_WRAPPERS`.
- sync itself back to `/root/.hermes/wolfy/mike_safe_autorepair.py` and profile copies.

Verification:

```bash
python /root/.hermes/scripts/mike_safe_autorepair.py
python /root/.hermes/scripts/mike_safe_autorepair.py   # second run should be silent
for f in \
  /root/.hermes/wolfy/wolfy_intraday_scanner_snapshot.py \
  /root/.hermes/scripts/wolfy_intraday_scanner_snapshot.py \
  /root/.hermes/profiles/mike/scripts/wolfy_intraday_scanner_snapshot.py \
  /root/.hermes/profiles/clerky/scripts/wolfy_intraday_scanner_snapshot.py; do
  python "$f" --help >/tmp/wolfy_intraday_help.out
done
```

For a non-mutating/small smoke, avoid strict data thresholds that can fail on one ticker:

```bash
/root/.hermes/scripts/wolfy_intraday_scanner_snapshot.py \
  --universe ticker-list --ticker-list SPY --max-workers 1 --min-ranked 0
# expect: exit 0, stdout 0 bytes, stderr 0 bytes
```

### 2. CLI smoke runners must be self-contained on a fresh temp fixture DB
Pytest fixtures can hide missing bootstrap logic. If an ops handoff says `python accountability_loop_smoke.py --db /tmp/new.db ... -> OK`, verify exactly that command on a brand-new temp path.

Safe repair for `accountability_loop_smoke.py`:
- Before running the loop, call a helper such as `_seed_fixture_candidate_if_needed(db_path, as_of)`.
- The helper should create only fixture SQLite tables/rows in the supplied DB path, not live Postgres rows and not real trade state.
- Seed one deterministic complete candidate (MSFT in this run) with scanner row, alpha lead, evidence, and Yang review so promotion -> recommendation -> Sentinel -> paper open -> outcome grade is exercised.
- Keep Postgres writes stubbed/captured in memory.

Verification:

```bash
cd /root/.hermes/wolfy
python -m pytest test_accountability_loop_smoke.py -q -o 'addopts='
rm -f /tmp/wolfy_accountability_smoke_fixture_review.db
python accountability_loop_smoke.py \
  --db /tmp/wolfy_accountability_smoke_fixture_review.db \
  --as-of 2026-06-01T18:00:00+00:00 >/tmp/accountability_smoke.json
python - <<'PY'
import json
r=json.load(open('/tmp/accountability_smoke.json'))['rows_created_or_updated']
assert r['recommendations_pending_review_created'] == 1
assert r['paper_trades_closed'] == 1
print(r)
PY
python -m pytest -q -o 'addopts='
```

## Kanban review clearance pattern
If a Wolfy Kanban card is blocked only on `review-required`, Mike can clear it after rerunning cited non-destructive verification. Comment with exact commands/output, then run:

```bash
hermes kanban --board wolfy complete <task_id>
hermes kanban --board wolfy dispatch
```

Do not add extra free-form completion arguments; put the detailed review summary in the comment first.
