# Hermes scheduler vs system crontab, and browser terminal discovery

Use this when a user asks what is in "crontab" or asks whether there is a browser-visible Hermes setup.

## Crontab distinction

Hermes cron jobs are not necessarily Linux user crontab entries.

Recommended sequence:
1. Run `crontab -l 2>&1` to answer the literal system-crontab question.
2. If it says `no crontab for root`, do not stop there when the context is Hermes. Run `hermes cron list --all` and summarize the Hermes scheduler jobs.
3. Make the distinction explicit in the answer: system crontab is empty; Hermes uses its own scheduler.

## Browser terminal discovery

For hosted Hermes setups, there may be a browser-accessible terminal container rather than a separate web dashboard.

Useful checks:
- `hermes status --all` for gateway/auth/scheduled-job status.
- `ss -ltnp` for listening ports.
- `docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'` for exposed containers.
- `docker inspect <container> --format '{{json .Config.Labels}}'` to find Traefik host rules and service ports.
- `curl -ksI https://<host>/` to verify whether it is alive.

Observed pattern: Hostinger-style Hermes container exposes `ttyd` on container port `4860`, often routed by Traefik via a host like `hermes-agent-<id>.<domain>`. HTTP 401 with `www-authenticate: Basic realm="ttyd"` means the web terminal is reachable and protected by Basic Auth.

Do not print recovered admin passwords into the chat. If the user needs it, give a local command they can run themselves to inspect `ADMIN_PASSWORD` from the container environment.