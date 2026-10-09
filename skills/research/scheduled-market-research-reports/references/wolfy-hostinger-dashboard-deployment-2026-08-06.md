# Wolfy Hostinger Dashboard Deployment — 2026-08-06

## Trigger

User asked whether anything could be done without human intervention for the newly built phone dashboard on a Hostinger VPS.

## Durable deployment pattern

When the VPS already runs Hostinger's Hermes/Traefik stack:

1. Inspect existing ingress before asking for DNS or hosting credentials:
   - `ss -ltnp` for ports 80/443 and Postgres/socket state.
   - `docker ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'`.
   - Existing compose files under `/docker/*/docker-compose.yml`.
   - Existing `.env` keys only by name; redact values except non-secret routing hostnames.
2. If Traefik is already active and `TRAEFIK_HOST` is a Hostinger wildcard hostname, a service can often be launched at:
   - `<service>.<TRAEFIK_HOST>`
   - Example: `dashboard.example.invalid` may resolve without custom DNS work when the provider wildcard is configured.
3. Create a dedicated compose directory such as `/docker/wolfy-dashboard/` with:
   - Generated `WOLFY_DASHBOARD_PIN` in `.env` with mode `0600`.
   - `COMPOSE_PROJECT_NAME=wolfy-dashboard`.
   - `TRAEFIK_HOST=<hostinger-host>`.
   - `WOLFY_POSTGRES_DSN=dbname=wolfy user=root host=/var/run/postgresql` when using the local Postgres socket.
   - Mount `/var/run/postgresql:/var/run/postgresql` if the container must use the host's Postgres Unix socket.
4. Use existing Traefik Docker labels:
   ```yaml
   labels:
     - traefik.enable=true
     - traefik.http.routers.${COMPOSE_PROJECT_NAME}.rule=Host(`${COMPOSE_PROJECT_NAME}.${TRAEFIK_HOST}`)
     - traefik.http.routers.${COMPOSE_PROJECT_NAME}.entrypoints=websecure
     - traefik.http.routers.${COMPOSE_PROJECT_NAME}.tls.certresolver=letsencrypt
     - traefik.http.services.${COMPOSE_PROJECT_NAME}.loadbalancer.server.port=8080
   ```
5. For a single-container dashboard on the same host, `network_mode: host` avoids Docker-provider reachability issues; keep the service on port 8080 and let Traefik proxy to it.
6. Deploy:
   ```bash
   cd /docker/wolfy-dashboard
   docker compose --env-file .env up -d --build
   ```
7. Verify more than `/healthz`:
   - Local `/healthz`.
   - Local authenticated `/api/summary` with `x-dashboard-pin` loaded from `.env`.
   - Public HTTPS `/healthz`.
   - Public HTTPS authenticated `/api/summary`.
   - Browser load of the landing page.

## Verification from this session

- Docker container: `dashboard-service-1`.
- Public URL example: `https://dashboard.example.invalid/`.
- Verified public HTTPS health and authenticated summary.
- Summary returned 30 timeline days, auto-discovered agents, 2 polls, 60-second refresh, and recommendation-attention data.

## Security notes

- Do not paste generated dashboard PINs into chat unless explicitly requested.
- Store the PIN in `/docker/wolfy-dashboard/.env` with mode `0600`.
- Prefer a non-superuser/read-mostly dashboard DB user later; the local socket/root path was a pragmatic same-host launch path.
- Keep dashboard writes narrow: notes and poll answers only; no strategy/recommendation/paper-trade mutation from v1.

## Human input still needed later

Only needed for custom branding/domain work:

- Desired custom domain/subdomain.
- DNS access or user points an A record to the VPS IP.
- Any preference to replace the Hostinger wildcard URL.
