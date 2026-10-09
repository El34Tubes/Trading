---
name: traefik-vps-app-deployments
description: Deploy and debug Docker web apps behind Traefik on VPS hosts, including Hostinger wildcard domains, HTTPS routing, and avoiding direct app-port exposure.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [traefik, docker, vps, hostinger, reverse-proxy, https, ssl]
    related_skills: [systematic-debugging, hermes-runtime-operations]
---

# Traefik VPS App Deployments

## When to use

Use this when deploying or troubleshooting a Docker/FastAPI/static app on a VPS that already uses Traefik for public HTTP/HTTPS routing, especially Hostinger VPS installs with domains like `*.srvNNNN.hstgr.cloud`.

Typical triggers:

- User reports `ERR_SSL_PROTOCOL_ERROR`, TLS/certificate errors, or “all my projects broke”.
- Adding a new dashboard/service to a VPS with existing Traefik-routed apps.
- Verifying whether a new container disturbed shared routing.
- Moving a web app from local port testing to public HTTPS.

## Principles

1. Treat cross-project breakage as a whole-VPS routing incident, not an app-only bug.
2. Reproduce with tight server-side loops before changing config.
3. Preserve existing services; avoid restarting Traefik unless logs/config prove it is necessary.
4. Prefer Traefik-only public exposure: app containers should use `expose`, not host `ports`, unless explicitly intended.
5. Never paste real `.env` secrets or dashboard PINs into chat/log summaries unless the user explicitly asks.

## Initial inventory

```bash
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'
ss -ltnp | grep ':80\|:443\|:8080\|:4860' || true
```

Expected healthy shared routing usually means Traefik is the only public listener on `:80` and `:443`. App ports should not be publicly bound unless there is a deliberate reason.

Inspect labels:

```bash
docker inspect $(docker ps -q) --format '{{.Name}} {{range $k,$v := .Config.Labels}}{{println $k "=" $v}}{{end}}'
```

Pitfalls from live Hostinger rollback work:

- In Bash, use `printf '%s\n' '--- section ---'` or `echo` for section headers; `printf '--- section ---'` can be parsed as an option by some shells and abort a broad diagnostic.
- Docker Go templates do not have a `contains` helper by default. For label filtering, prefer `docker inspect ... | python3`/`jq` or print all labels and grep outside the template.
- If the user asks for "out-of-the-box Hostinger" cleanup, remove only the newly-created app/router/cert artifacts. Do not remove `/docker/traefik`, the Docker socket provider, existing project networks, or unrelated ACME certificates.

Inspect compose files, redacting secrets:

```bash
for f in /docker/*/docker-compose.yml /docker/*/.env; do
  echo "--- $f"
  # Print compose files normally; print only non-sensitive .env keys/placeholder values.
done
```

## HTTPS verification loop

Test every known route over IPv4 and IPv6:

```bash
for host in dashboard.example.invalid app-one.example.invalid agent.example.invalid; do
  echo "### $host"
  curl -4 -skS -o /dev/null -w 'ipv4 https=%{http_code} ip=%{remote_ip}\n' "https://$host/" || true
  curl -6 -skS -o /dev/null -w 'ipv6 https=%{http_code} ip=%{remote_ip}\n' "https://$host/" || true
  echo | openssl s_client -connect "${host}:443" -servername "$host" 2>/dev/null | openssl x509 -noout -subject -issuer -dates || true
done
```

`200` and authenticated `401` can both be healthy. For TLS diagnosis, the key signals are successful handshake, expected certificate subject, valid issuer/dates, and no protocol failure.

## Safer Traefik-only compose pattern

Avoid this for a Traefik-managed public app:

```yaml
network_mode: host
ports:
  - "8080:8080"
```

Use this instead:

```yaml
services:
  app:
    restart: unless-stopped
    expose:
      - "8080"
    labels:
      - traefik.enable=true
      - traefik.http.routers.${COMPOSE_PROJECT_NAME}.rule=Host(`${COMPOSE_PROJECT_NAME}.${TRAEFIK_HOST}`)
      - traefik.http.routers.${COMPOSE_PROJECT_NAME}.entrypoints=websecure
      - traefik.http.routers.${COMPOSE_PROJECT_NAME}.tls.certresolver=letsencrypt
      - traefik.http.services.${COMPOSE_PROJECT_NAME}.loadbalancer.server.port=8080
```

Then deploy from the app compose directory:

```bash
docker compose --env-file .env up -d --build
```

## Emergency rollback when user suspects cross-project damage

If the user says a new deployment “messed something up”, “every other project broke”, or explicitly asks to revert, prioritize removing the newly introduced public router/container from the live VPS before debating root cause. The goal is to restore user trust and eliminate the new variable quickly.

If the user asks to remove “any proxy/Traefik non-standard out-of-the-box Hostinger stuff we created,” treat that as a deeper artifact cleanup request: remove only the new app’s container/router/files/volume/image plus app-specific cert/cache references, while preserving Hostinger’s original Traefik container, Docker socket provider, existing routers, and existing app certificates.

Minimal live rollback:

```bash
cd /docker/<new-app>
docker compose --env-file .env down --remove-orphans
rm -rf /docker/<new-app>              # only if it was created for this deployment
# optional cleanup after confirming no data must be preserved:
docker volume rm <project>_<volume> 2>/dev/null || true
docker rmi <image>:latest 2>/dev/null || true
```

Then verify the new route is gone and existing routes still answer:

```bash
docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'
ss -ltnp | grep ':80\|:443\|:8080' || true
for host in <existing-host-1> <existing-host-2> <removed-host>; do
  echo "### $host"
  curl -4 -skS -o /dev/null -w 'ipv4 https=%{http_code} err=%{errormsg}\n' "https://$host/" || true
  curl -6 -skS -o /dev/null -w 'ipv6 https=%{http_code} err=%{errormsg}\n' "https://$host/" || true
done
```

Expected after rollback: existing apps return their normal `200`/`401`, the removed route returns `404`, and only Traefik owns public `:80`/`:443`. After the live rollback, revert source/deployment commits selectively; do not touch unrelated dirty files in the Hermes profile or other projects.

### Removing stale app-specific ACME/cert artifacts

A removed Traefik route can leave its certificate cached in Traefik’s ACME JSON. Do not delete the whole ACME volume. Back it up, remove only the certificate whose `domain.main` equals the removed app host, then restart Traefik and verify the remaining domains still handshake.

```bash
ACME=/var/lib/docker/volumes/traefik_traefik-letsencrypt/_data/acme.json
cp "$ACME" "${ACME}.pre-<app>-cert-removal.$(date +%Y%m%d%H%M%S)"
python3 - <<'PY'
import json, os
p='/var/lib/docker/volumes/traefik_traefik-letsencrypt/_data/acme.json'
remove='removed-app.example.com'
data=json.load(open(p))
for body in data.values():
    if isinstance(body, dict) and isinstance(body.get('Certificates'), list):
        body['Certificates']=[c for c in body['Certificates'] if (c.get('domain') or {}).get('main') != remove]
json.dump(data, open(p,'w'), separators=(',', ':'))
os.chmod(p, 0o600)
PY
docker restart traefik-traefik-1
```

After verifying existing routes, delete the temporary backup if the user asked for no remaining artifacts from the removed app. Scan for stale references with `grep -RIl` over `/docker`, the app repo/deployment paths, and the ACME data directory.

## Post-fix verification

```bash
ss -ltnp | grep ':80\\|:443\\|:8080' || true
# Should show Traefik on 80/443 and no public 8080 unless intentionally exposed.

for host in dashboard.example.invalid app-one.example.invalid agent.example.invalid; do
  curl -4 -skS -o /dev/null -w "$host %{http_code}\\n" "https://$host/" || true
done
```

If server-side TLS is clean but the user still sees `ERR_SSL_PROTOCOL_ERROR`, ask for the exact address-bar URL and check for stale `:8080`, browser cache, Wi-Fi DNS/cache, or Hostinger panel preview/proxy cache. If the user asks for a revert anyway, do the rollback first and continue diagnosis only after the new route is removed.

## References

- `references/hostinger-traefik-https-debugging.md` — session-derived Hostinger/Trafik incident checklist and exact probes.
