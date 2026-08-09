# Wolfy Command Dashboard

Mobile-first, PIN-protected, platform-agnostic public website for Wolfy/Hermes progress tracking.

## What v1 shows

- Daily progress timeline first.
- All discovered agents/profiles from `agent_tasks` and `agent_runs`.
- Environment health metrics from `system_metrics`.
- Recommendations and items needing attention from `recommendations`.
- Paper-trade summary from `paper_trades`.
- Auto-suggested interview polls and dashboard-submitted poll answers.
- Manual notes/status overrides.
- 60-second client refresh.

## Safety model

- PIN required for API reads and writes.
- No secrets embedded in the image.
- Read-mostly dashboard; write endpoints only store manual notes and poll answers in a JSON data volume.
- Does not execute trades or mutate Wolfy recommendations/paper trades.

## Local run

```bash
cd /root/.hermes/wolfy
export WOLFY_DASHBOARD_PIN='change-me'
export WOLFY_POSTGRES_DSN='dbname=wolfy user=root host=/var/run/postgresql'
python3 dashboard_app.py
```

Open:

```text
http://localhost:8080
```

## Docker/VPS run

Create a `.env` file next to `docker-compose.dashboard.yml` on the VPS:

```dotenv
WOLFY_DASHBOARD_PIN=choose-a-strong-pin
WOLFY_POSTGRES_DSN=postgresql://wolfy:REDACTED@postgres-host:5432/wolfy
```

Then:

```bash
docker compose -f docker-compose.dashboard.yml up -d --build
```

Expose the service behind your VPS reverse proxy/TLS provider. The app listens on container port `8080`.

## API

```text
GET  /healthz
GET  /api/summary                 header: x-dashboard-pin
POST /api/notes                   header: x-dashboard-pin
POST /api/polls/{poll_id}/answer  header: x-dashboard-pin
```

`/api/summary` is the source for the landing page and updates every 60 seconds in the browser.
