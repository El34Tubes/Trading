---
name: hermes-runtime-operations
description: "Operate and validate a live Hermes Agent install: doctor/status checks, optional dependency installation, runtime venv package fixes, and smoke-test verification."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [hermes, operations, validation, dependencies, troubleshooting]
    created_by: agent
---

# Hermes Runtime Operations

Use this skill when the user asks to validate what is working/not working in a live Hermes Agent install, install optional/system dependencies, or verify that a Hermes runtime feature works after setup changes.

This is an operations/checklist skill, not a replacement for the bundled `hermes-agent` reference skill. Load `hermes-agent` first for authoritative CLI/config commands, then use this skill for the practical validation workflow.

## Workflow

1. Establish baseline health.
   - Run `hermes status --all` to see provider, gateway, platform, and high-level environment status.
   - Run `hermes doctor` for dependency/config/tool availability diagnostics.
   - Run quick direct probes for the items doctor complains about, e.g. `node --version`, `npm --version`, `rg --version`, or a Python import in the Hermes venv.

2. Separate installable dependencies from credential/config gaps.
   - Installable examples: `nodejs`, `npm`, `ripgrep`, optional Python packages such as `python-telegram-bot`.
   - Credential/config examples: API keys, OAuth login, provider-specific tokens, Home Assistant/Spotify/Feishu setup, CDP endpoint configuration.
   - Do not describe unconfigured credentials as broken tools; report them as needing setup.

3. Install OS packages with the system package manager.
   - On Ubuntu/Debian:
     ```bash
     apt-get update
     DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs npm ripgrep
     ```
   - Verify immediately:
     ```bash
     node --version
     npm --version
     rg --version | head -1
     ```

4. Install optional Python packages into the Hermes runtime venv, not an unrelated system Python.
   - Resolve the Hermes venv path from the install; common path:
     `/usr/local/lib/hermes-agent/venv/bin/python`
   - Prefer `uv pip install --python /path/to/venv/bin/python <package>`.
   - If `apt-get install python3-<pkg>` makes `/usr/bin/python3` work but Hermes cron/tools still fail, the missing package is in the wrong Python; install into the Hermes venv and verify with that exact interpreter.
   - Example:
     ```bash
     uv pip install --python /usr/local/lib/hermes-agent/venv/bin/python python-telegram-bot
     /usr/local/lib/hermes-agent/venv/bin/python -c 'import telegram; print(telegram.__version__)'
     ```
   - For HTML parsing dependencies such as `bs4`, see `references/hermes-runtime-optional-python-deps.md`.

5. Let Hermes auto-fix its own command/path issues.
   - Run `hermes doctor --fix` after installing dependencies.
   - This can repair items like a missing `~/.local/bin/hermes` symlink.
   - If `hermes doctor` reports `Skills Hub directory not initialized`, run `hermes skills list` once and then re-run `hermes doctor`; this initializes the hub/lock state without changing installed skills.

6. Verify with both diagnostics and live smoke tests.
   - Re-run `hermes doctor`.
   - For profile-scoped cron operations, check the profile that owns the jobs explicitly (`hermes --profile <name> cron list --all`). Do not rely only on the active profile: scheduled ops jobs may run from a Mike/admin profile while production jobs live under `default`, `clerky`, or another worker profile. If an ops pre-run/triage script only prints the active profile's empty cron list, fix the script to include the production profile cron listing as deterministic context so future runs do not rediscover or misreport the same issue.
   - For script-only/no-agent watchdogs, empty stdout with exit code 0 is normally a healthy silent run. Report only nonzero exits or actionable output.
   - For Postgres no-agent helpers that update rows via `psycopg`, explicitly `conn.commit()` before exit and verify persistence with a follow-up `psql` query plus a second silent run. Do not trust a `RETURNING` printout alone; uncommitted subprocess updates can look successful while leaving rows unchanged.
   - For Postgres-backed coordination ledgers, watch for context generators that repeatedly re-select stale local `in_progress` work and create duplicate `blocked`/`duplicate-or-already-claimed` `agent_runs`. The safe fix is usually to have context generators claim only fresh queued work, leave stale `in_progress` cleanup to the watchdog, and verify with a post-fix query such as `count(*) where error_message='duplicate-or-already-claimed' and started_at > <fix time>`.
   - For context-script smoke tests that intentionally call helpers which create `agent_runs.status='started'` rows or claim temporary tasks, finish the temporary smoke rows explicitly with `records_created=0` and a smoke-test summary so the operations pass does not introduce stale-run noise; verify `agent_runs`/`agent_tasks` status counts afterward. See `references/wolfy-context-smoke-cleanup-2026-06-02.md`.
   - For durable Wolfy SQLite schema drift, prefer non-destructive compatibility aliases over destructive rewrites. If newer diagnostics query aliases such as `strategy_rules.name/status/asset_class`, add nullable/default alias columns, backfill from canonical fields, add idempotent init-script guards/triggers, and verify the exact query plus the affected cron context. See `references/wolfy-runtime-compatibility-aliases.md`.
   - Treat `recent errors` log tails as triage leads, not current truth: historical pytest/tool failures may already be fixed by another worker. Before editing code, rerun the exact relevant tests plus the broader local smoke suite when cheap; if they now pass, do not invent a fix or report stale failures as active blockers.
   - When profile cron jobs use relative `script` paths, verify the wrapper exists under that profile's `scripts/` directory or switch the job to a valid absolute script path. Keeping global and profile wrapper scripts synchronized is a safe reversible repair.
   - If a diagnostic references an older script name after an implementation was renamed, prefer a tiny compatibility wrapper that delegates to the live implementation, then teach the script-only autorepair loop to recreate that wrapper. Verify the wrapper and the live implementation both exit 0 before reporting the issue fixed.
   - For profile/default cron script wrappers, check every layer that might be invoked: the live implementation, the global wrapper under `/root/.hermes/scripts/`, and profile wrappers under `~/.hermes/profiles/<name>/scripts/`. A profile wrapper can be healthy while a default-profile cron still calls a stale or missing global wrapper. When repairing, update the autorepair script's canonical source and sync the global/profile copies, then verify all wrapper paths directly.
   - When a compatibility wrapper is safe and generic (for example a renamed Wolfy helper such as `wolfy_embed_knowledge_chunks.py` delegating to `embed_knowledge_chunks.py`), sync it to every operations profile that may run diagnostics or handoffs, not only the profile that currently owns the cron job. In Wolfy operations this means checking the live implementation, `/root/.hermes/wolfy/<legacy>.py`, `/root/.hermes/scripts/<legacy>.py`, `/root/.hermes/profiles/mike/scripts/<legacy>.py`, and `/root/.hermes/profiles/clerky/scripts/<legacy>.py` when relevant. Teach the deterministic autorepair script to preserve the same set so the fix survives future runs.
   - If an autorepair script itself is part of the operations workflow, include that script in its own global-to-profile sync allowlist too. Otherwise profile-scoped diagnostics can fail with a missing autorepair wrapper even while the global cron job works. Verify by invoking the global wrapper and each profile copy directly. See `references/profile-autorepair-self-sync.md`.
   - When a renamed context helper is used by cron (for example Alpha Search moving to `alpha_search_context.py` while jobs/diagnostics still reference `wolfy_alpha_search_context.py`), preserve a tiny compatibility wrapper in the live Wolfy directory, global scripts directory, and relevant profile script directories. Teach the no-agent autorepair loop to recreate/sync the wrapper and to keep its own Wolfy-local copy current. Smoke-test every wrapper path, then close any context-created `agent_runs` rows with `records_created=0` so verification does not leave stale `started` noise. See `references/wolfy-alpha-context-wrapper-sync.md`.
   - For profile-scoped doctor output, remember that cron/gateway profile wrappers may set `HOME` to the profile home (e.g. `/root/.hermes/profiles/<name>/home`). `hermes doctor --fix` may create `~/.local/bin/hermes` and Playwright browser caches under that profile home, not `/root`; verify with the same `hermes --profile <name> doctor` invocation that reported the issue.
   - If `hermes doctor` reports `Playwright Chromium not installed`, the safe repair is `cd /usr/local/lib/hermes-agent && npx playwright install --with-deps chromium`, then re-run doctor for each relevant profile. Treat the resulting browser availability as install state, not as a durable claim that browser tools were broken.
   - For browser automation, perform a tiny navigation smoke test such as `https://example.com` and confirm a successful title/snapshot.
   - For messaging/file delivery, create a small throwaway file under `/tmp`, send it with `MEDIA:/tmp/...` to the configured platform/channel, and report the returned platform/chat/message IDs. If the first attempt fails with Discord `403 Missing Access`, check whether the gateway/platform has reconnected or the home channel was refreshed, then retry before concluding the channel is inaccessible.
   - For inbound Discord tests, distinguish three layers: message exists in Discord, gateway observed it, and Hermes accepted it into an agent session. Check Discord channel history/API, `~/.hermes/logs/gateway.log`, and `~/.hermes/state.db`. If the log says `Unauthorized user`, report that the message reached the gateway but was rejected before agent processing.
   - Report actual versions and actual remaining warnings from tool output.

## Messaging attachment smoke test

Use this pattern when the user asks whether Hermes can “drop a file” into a gateway channel:

```text
write_file('/tmp/hermes-<platform>-file-test.txt', '...short test payload...')
send_message(target='discord:<channel_id-or-home>', message='Test upload\n\nMEDIA:/tmp/hermes-<platform>-file-test.txt')
```

Verification is the `send_message` result, not just the absence of an exception. Capture and report `platform`, `chat_id`, and `message_id` when present. Treat credential/channel permission errors as setup issues; do not encode them as durable tool failures.

More detail: `references/messaging-attachment-smoke-tests.md`.

## Reporting conventions

- Keep the result concise and grouped as: installed, fixed, verified, remaining.
- Distinguish “remaining because credentials/config are missing” from “remaining because system dependencies are missing.”
- Avoid persistent negative claims like “browser is broken.” Say what setup is missing or what smoke test now confirms.

## References

- `references/optional-dependencies-2026-05.md` — concrete dependency-install and verification transcript distilled from a live Hermes runtime cleanup.
- `references/discord-inbound-gateway-checks.md` — how to verify whether a Discord channel message was merely present, gateway-observed, or actually accepted into a Hermes session.
- `references/profile-cron-ops-triage.md` — compact checklist for profile-scoped cron operations, wrapper sync, usage-ledger sync, and interpreting silent no-agent watchdogs.
- `references/profile-autorepair-self-sync.md` — Mike/Wolfy pattern for teaching script-only autorepair to sync its own profile wrappers and verifying each invocation layer.
- `references/wolfy-runtime-compatibility-aliases.md` — safe Wolfy runtime repairs for schema alias drift, smoke-test `agent_runs` cleanup, and document-extraction package verification.
