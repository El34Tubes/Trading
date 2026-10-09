# Wolfy dashboard current snapshot + poll write-back (2026-08-07)

## Session learning

The user corrected the mobile dashboard direction after initial launch:

- They do **not** want the default dashboard to be a historical daily timeline.
- They want a point-in-time **current** command snapshot.
- They want interview polls to be clickable and to write back.
- Poll answers should represent the latest/current answer per poll rather than an accumulated history unless the user explicitly asks for audit history.

## Implementation pattern

For `dashboard_app.py`-style FastAPI dashboards:

1. API shape should return `current`, not `timeline`, by default:
   - `current.as_of_date`
   - `current.tasks.queued`
   - `current.tasks.in_progress`
   - `current.tasks.failed`
   - `current.runs.active`
   - `current.recommendations.pending_attention`
   - `current.paper_trades.open`
   - `current.paper_trades.total_current`
2. Landing page first module should be `Current Snapshot`.
3. Keep the dashboard summary-level; do not dump job history unless explicitly requested.
4. Poll buttons should call `POST /api/polls/{poll_id}/answer` with the selected choice and PIN header.
5. Store poll answers in a small side store (JSON volume is acceptable for v1), but replace any previous answer for the same `poll_id` so the dashboard displays current answers.
6. Render `Current answers`, not `Recent answers`, to avoid implying history is the primary model.

## Tests added/expected

Use TDD for these behaviors:

- Snapshot test asserts `"timeline" not in snapshot` and `"current" in snapshot`.
- Snapshot test asserts current task/run/recommendation counts.
- API test posts to `/api/polls/{poll_id}/answer` and then verifies `/api/summary` returns the answer.
- Persistence test writes two answers for the same poll and asserts only the latest remains.

## Verification commands from the session

```bash
cd /root/.hermes/wolfy
export WOLFY_POSTGRES_DSN='dbname=wolfy user=root host=/var/run/postgresql'
python3 -m pytest test_dashboard_app.py -q
python3 -m pytest -q
```

Observed before final label-only change:

```text
test_dashboard_app.py => 6 passed
full suite => 130 passed
```

Live Hostinger verification used:

```bash
cd /docker/wolfy-dashboard
docker compose --env-file .env up -d --build
curl -fsS -H "x-dashboard-pin: $WOLFY_DASHBOARD_PIN" \
  https://wolfy-dashboard.srv1718608.hstgr.cloud/api/summary
curl -fsS -X POST \
  -H "content-type: application/json" \
  -H "x-dashboard-pin: $WOLFY_DASHBOARD_PIN" \
  -d '{"choice":"paper logging","note":"live click-equivalent verification"}' \
  https://wolfy-dashboard.srv1718608.hstgr.cloud/api/polls/next-build/answer
```

Expected verified result:

```text
has_current: true
has_timeline: false
latest_poll_id: next-build
latest_choice: paper logging
```

## Pitfalls

- `/healthz` is insufficient; it can pass while authenticated `/api/summary` fails due schema/SQL errors.
- Public route may briefly return 502 during Docker/Traefik restart; wait and recheck `/healthz` plus authenticated `/api/summary`.
- If testing locally sets `WOLFY_POSTGRES_DSN=dbname=wolfy`, reset it before running the full suite because some tests compare the shared default socket DSN.
- Do not expose the dashboard PIN in chat unless the user explicitly asks; use the already-configured PIN or store it in `/docker/wolfy-dashboard/.env`.
