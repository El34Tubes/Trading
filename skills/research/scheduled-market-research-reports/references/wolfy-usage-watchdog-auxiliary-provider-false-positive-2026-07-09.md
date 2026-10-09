# Wolfy usage watchdog: auxiliary-provider false positives (2026-07-09)

## Trigger

The user questioned why Mike was reporting 429/usage-limit trouble while live chat on the production model still worked. The watchdog had recently emitted Discord alerts even though the active `openai-codex` credential was clear.

## Finding

The false alerts came from log lines emitted by Hermes auxiliary/fallback providers, not from the production Wolfy/Mike provider:

- `agent.auxiliary_client: Auxiliary: marking openrouter unhealthy ... payment / credit error`
- `agent.auxiliary_client: Auxiliary: marking nous unhealthy ... payment / credit error`

Those lines are useful diagnostic noise for auxiliary compression/fallback behavior, but they are **not** sufficient evidence that Wolfy/Mike LLM cron jobs should be paused or that the user-facing model is usage-limited.

## Durable fix pattern

For `/root/.hermes/scripts/wolfy_usage_limit_watchdog.py` and synced profile copies:

1. Scope live provider checks to the production provider (`hermes --profile default auth list openai-codex`) rather than broad all-provider auth checks.
2. Treat production-provider evidence as actionable only when it contains concrete quota/rate-limit terms such as:
   - `usage_limit_reached`
   - `HTTP 429`
   - `status 429`
   - `usage limit has been reached`
   - `rate limit`
   - `too many requests`
3. Ignore auxiliary-provider lines for gating/alerting:
   - `agent.auxiliary_client:`
   - `payment / credit error` from OpenRouter/Nous fallback paths
   - auxiliary compression fallback exhaustion
4. Do not scan stale backup directories under active log roots. Move old backups out of `/root/.hermes/logs/` if scanners recurse or humans grep broadly.
5. Require dated same-day evidence for log-based active-limit checks; do not let undated traceback fragments carry a stale 429 forward.
6. When provider auth is clear, watchdog output should be silent and should not recommend pausing Jonah/Mike.
7. Remove large `hermes insights` dumps from watchdog alerts; if a limit is real, print only the event/timestamp and the operational action.

## Verification shape

Use script-only checks:

- `hermes --profile default auth list openai-codex` shows configured credential with no limit text.
- Watchdog state shows `limited_active: false` and `paused_llm_jobs: []`.
- Active `agent.log`/`errors.log` have no production quota-pattern matches after trimming stale/false lines.
- Direct watchdog run emits zero bytes when no current production-provider limit is active.

## User-facing wording

Be direct: "That was a false fire from auxiliary provider warnings, not a real Mike/Codex usage limit." Then list the concrete trims/patches and current state. Do not paste raw dashboards or repeated quota lines unless the user asks for detail.
