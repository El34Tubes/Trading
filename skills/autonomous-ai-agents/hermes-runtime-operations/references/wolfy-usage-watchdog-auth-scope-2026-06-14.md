# Wolfy usage watchdog auth probe scoping — 2026-06-14

## Problem pattern

A script-only usage-limit watchdog was correctly checking the production profile, but it called:

```bash
hermes --profile default auth list
```

That enumerates every auth provider. In the Wolfy/default profile, an unrelated Copilot credential was sourced from `GITHUB_TOKEN` as a classic `ghp_*` token. Hermes logged repeated warnings that classic PATs are unsupported by the Copilot API, even though Wolfy's active LLM provider was `openai-codex` and the Copilot credential was not part of the production cron model path.

The result was noisy operations logs and misleading watchdog evidence.

## Durable fix

Scope the watchdog's auth-health probe to the provider that actually powers the production cron jobs:

```python
auth = run(['hermes', '--profile', 'default', 'auth', 'list', 'openai-codex'])
```

Do not remove or reinterpret unrelated credentials unless the user explicitly asks. A classic `GITHUB_TOKEN` may still be useful for GitHub API/skills hub rate limits; the fix is to avoid probing it as Copilot health when Copilot is not the active Wolfy provider.

## Verification recipe

After patching the live script and any global/profile wrapper copies:

```bash
python3 /root/.hermes/scripts/wolfy_usage_limit_watchdog.py >/tmp/watchdog.out 2>/tmp/watchdog.err
wc -c /tmp/watchdog.out /tmp/watchdog.err
python3 /root/.hermes/scripts/mike_safe_autorepair.py
python3 /root/.hermes/scripts/mike_safe_autorepair.py  # second run should be silent
```

Also verify the production cron status and relevant ledgers remain healthy:

```bash
/root/.hermes/wolfy/check_postgres_requirements.py
hermes --profile default cron list --all
```

Expected healthy result: watchdog stdout/stderr are zero bytes when no new quota events exist, autorepair's second run is silent, and default-profile cron jobs remain active.

## Skill-level lesson

For quota/usage watchdogs, distinguish the production model provider from unrelated configured auth providers. Use provider-scoped `hermes auth list <provider>` for health checks; reserve all-provider listing for explicit credential inventory tasks.
