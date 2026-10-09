# Wolfy mobile command dashboard pattern — 2026-08-06

## User requirements captured

- Platform-agnostic public website, not tied to Discord/Telegram.
- Dockerized app ready for any VPS.
- PIN/password protection.
- Mobile-first landing page with **daily progress timeline first**.
- Read-mostly dashboard plus manual notes/status overrides.
- Include all auto-discovered profiles/agents, not only Wolfy.
- Separate summary-level modules: daily progress/jobs by day, agents, environment health, recommendations/approval attention, paper trades, manual notes, and interview polls.
- Interview polls should be LLM-suggested/agent-suggested and answerable from the dashboard.
- Refresh about every 60 seconds.

## Implemented v1 shape

Files:

- `wolfy/dashboard_app.py` — FastAPI app, single-file mobile UI, PIN-protected API.
- `wolfy/test_dashboard_app.py` — TDD tests for snapshot aggregation, PIN auth, note persistence, poll answer persistence.
- `wolfy/Dockerfile.dashboard` — container image.
- `wolfy/docker-compose.dashboard.yml` — VPS-ready compose file.
- `wolfy/dashboard.env.example` — committed template for required env vars; never commit real `.env`.
- `wolfy/Caddyfile.dashboard.example` — example TLS reverse proxy for public launch.
- `wolfy/dashboard_requirements.txt` — pinned dashboard dependencies.
- `wolfy/DASHBOARD_README.md` — launch/deploy/API notes and user handoff checklist.

Data sources:

- `agent_tasks` for jobs/tasks and daily progress.
- `agent_runs` for agent activity and token/cost summaries.
- `recommendations` for pending/paper/approval attention.
- `paper_trades` for paper ledger visibility.
- `system_metrics` for environment health.
- JSON note store for phone-entered manual notes/status overrides and poll answers.

API shape:

- `GET /healthz`
- `GET /api/summary` with `x-dashboard-pin`
- `POST /api/notes` with `x-dashboard-pin`
- `POST /api/polls/{poll_id}/answer` with `x-dashboard-pin`

Verification from build session:

- `python3 -m pytest test_dashboard_app.py -q` → `4 passed`.
- `python3 -m pytest -q` → `128 passed`.
- Local uvicorn smoke on port 18080: `/healthz` ok, `/api/summary` ok with PIN, timeline=30, agents discovered, polls=2, recommendation attention=49.
- Browser smoke confirmed landing page rendered and loaded data after PIN.
- `docker build -f wolfy/Dockerfile.dashboard -t wolfy-dashboard:test .` succeeded.
- Commit pushed: `f5cfef2ffb05997fedc2acc16f768d74992bb44c` (`wolfy(dashboard): add mobile command dashboard`).
- Follow-up deployment checklist/env/Caddy examples were added and pushed in commit `117864db5ea40b290e2afd2ab724740330f74b1b` (`wolfy(dashboard): add VPS deployment checklist`).

## Public launch checklist

Before claiming the dashboard is publicly launched, collect or verify:

1. Domain/subdomain, e.g. `wolfy.example.com`.
2. VPS target/IP or permission to provision/use one.
3. DNS access or confirmation the user will point the record.
4. Final dashboard PIN/password via a secure path.
5. Postgres DSN reachable from the VPS, preferably for a read-mostly dashboard DB user.
6. TLS/reverse proxy preference; Caddy is the default recommendation when unspecified.

Use `dashboard.env.example` as the template, keep real `.env` untracked, then run:

```bash
docker compose -f docker-compose.dashboard.yml --env-file .env up -d --build
```

## Pitfalls / durable lessons

- Do not assume compatibility alias columns exist across `agent_runs` and `agent_tasks`. In this environment `agent_runs` has `agent_name` but no `agent`; `agent_tasks` has multiple aliases. Query conservatively or inspect schema before writing dashboard SQL.
- Browser/dashboard smoke should test the actual authenticated API, not just `/healthz`; `/healthz` can pass while summary SQL fails.
- PIN auth can be a simple header for v1 (`x-dashboard-pin`) but public deployment should sit behind TLS/reverse proxy.
- Keep dashboard write endpoints narrow: manual notes and poll answers only. Do not mutate recommendations, paper trades, cron jobs, or strategy state from v1.
- Keep generated dashboard state in a data volume (`/data/dashboard_notes.json`) and keep secrets/config in env vars (`WOLFY_DASHBOARD_PIN`, `WOLFY_POSTGRES_DSN`).
- When using background uvicorn for smoke tests, kill tracked process sessions afterward and verify `ss -ltnp | grep ':18080\|:8080'` is empty before telling the user no test server is still running.
