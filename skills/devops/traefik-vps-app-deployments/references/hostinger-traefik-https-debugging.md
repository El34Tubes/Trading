# Hostinger Traefik HTTPS Debugging Reference

Session pattern: User reported Hostinger `ERR_SSL_PROTOCOL_ERROR` and then clarified “not just this project, every other one broke” after deploying a new dashboard.

## Observed environment pattern

- `/docker/traefik/docker-compose.yml` ran Traefik in `network_mode: host` and owned public `:80`/`:443`.
- Existing projects used Docker labels like:
  - `traefik.enable=true`
  - `traefik.http.routers.<name>.rule=Host(`<name>.srvNNNN.hstgr.cloud`)`
  - `traefik.http.routers.<name>.entrypoints=websecure`
  - `traefik.http.routers.<name>.tls.certresolver=letsencrypt`
  - `traefik.http.services.<name>.loadbalancer.server.port=<internal-port>`
- Hostinger wildcard domains resolved both A and AAAA records.

## What went wrong / durable lesson

A newly deployed dashboard was initially run with `network_mode: host`, making Uvicorn listen directly on public `0.0.0.0:8080` while Traefik also served 80/443. Server-side HTTPS to the real domain worked, but the direct public app port was risky and could produce browser `ERR_SSL_PROTOCOL_ERROR` if the user or Hostinger preview hit `https://domain:8080`.

Fix: remove `network_mode: host` and host `ports`; use Docker bridge `expose` plus Traefik labels. After redeploy, `ss -ltnp` should show only Traefik on public 80/443 and no app listener on public 8080.

## Exact probes used

```bash
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'
ss -ltnp | grep ':80\|:443\|:8080\|:4860\|:32768' || true
```

```bash
for host in dashboard.example.invalid app-one.example.invalid agent.example.invalid; do
  echo "### $host"
  curl -4 -skS -o /dev/null -w 'ipv4 https=%{http_code} ip=%{remote_ip}\n' "https://$host/" || true
  curl -6 -skS -o /dev/null -w 'ipv6 https=%{http_code} ip=%{remote_ip}\n' "https://$host/" || true
done
```

```bash
for host in dashboard.example.invalid app-one.example.invalid agent.example.invalid; do
  echo "### $host"
  echo | openssl s_client -connect "${host}:443" -servername "$host" 2>/dev/null | openssl x509 -noout -subject -issuer -dates || echo openssl_failed
done
```

## Safe compose pattern

```yaml
services:
  wolfy-dashboard:
    image: wolfy-dashboard:latest
    restart: unless-stopped
    expose:
      - "8080"
    env_file:
      - .env
    labels:
      - traefik.enable=true
      - traefik.http.routers.${COMPOSE_PROJECT_NAME}.rule=Host(`${COMPOSE_PROJECT_NAME}.${TRAEFIK_HOST}`)
      - traefik.http.routers.${COMPOSE_PROJECT_NAME}.entrypoints=websecure
      - traefik.http.routers.${COMPOSE_PROJECT_NAME}.tls.certresolver=letsencrypt
      - traefik.http.services.${COMPOSE_PROJECT_NAME}.loadbalancer.server.port=8080
```

## Reporting and rollback guidance

If all routes test healthy server-side, say so with concrete status codes. Do not dismiss the user’s report: remove risky exposure if found, then ask for the exact address-bar URL/screenshot if the client still fails.

If the user then says the deployment may have messed up other projects or asks to revert, stop defending the diagnosis and remove the new app from the live router first. In this session the safe rollback sequence was:

```bash
cd /docker/wolfy-dashboard
docker compose --env-file .env down --remove-orphans
rm -rf /docker/wolfy-dashboard
docker volume rm wolfy-dashboard_wolfy_dashboard_data 2>/dev/null || true
docker rmi wolfy-dashboard:latest 2>/dev/null || true
```

Then verify:

```bash
docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'
ss -ltnp | grep ':80\|:443\|:8080' || true
for host in app-one.example.invalid agent.example.invalid dashboard.example.invalid; do
  curl -4 -skS -o /dev/null -w 'ipv4 https=%{http_code} err=%{errormsg}\n' "https://$host/" || true
  curl -6 -skS -o /dev/null -w 'ipv6 https=%{http_code} err=%{errormsg}\n' "https://$host/" || true
done
```

Expected: existing projects return their normal auth/status (`401` in this case), the removed app returns `404`, and there is no public app listener on `:8080`. Only after the live rollback should you selectively revert repo commits, avoiding unrelated dirty files.

## Full artifact cleanup when the user wants “no non-standard proxy stuff”

If the user asks to remove any non-standard proxy/Traefik pieces created together, also clean stale app-specific ACME entries after the container/router is gone.

Inventory first:

```bash
docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' | grep -Ei 'wolfy|dashboard|traefik|app-one|hermes' || true
docker network ls --format '{{.Name}}\t{{.Driver}}' | grep -Ei 'wolfy|dashboard|traefik|app-one|hermes' || true
docker volume ls --format '{{.Name}}' | grep -Ei 'wolfy|dashboard|traefik|caddy' || true
grep -RIl --exclude-dir=.git --exclude='*.pyc' --exclude='*.log' -E 'wolfy-dashboard|Caddyfile|traefik\.http\.routers\.wolfy|dashboard\.srv' /docker /root/.hermes/wolfy /var/lib/docker/volumes/traefik_traefik-letsencrypt/_data 2>/dev/null | sort || true
```

To remove only one stale certificate from Traefik ACME storage, parse `acme.json`, filter out the certificate with `domain.main == <removed-host>`, preserve the rest, `chmod 600`, then restart Traefik. In the Hostinger incident, the final ACME domains were only the original app hosts, with `contains_wolfy_dashboard=false`.

Final acceptance criteria:

- Docker containers: only original Hostinger apps plus Traefik.
- Public listeners: only Traefik on `:80` and `:443`; no `:8080`, `:2019`, or `:8443`.
- ACME domains contain only original Hostinger app domains.
- `grep` finds no removed-app/Caddy/custom-router references in `/docker`, the repo deployment paths, or ACME data.
- Existing routes still return their expected `200`/`401`; removed host returns `404` or Traefik default cert/no app route.
