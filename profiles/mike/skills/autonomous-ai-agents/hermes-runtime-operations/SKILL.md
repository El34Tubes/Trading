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
   - Installable examples: `nodejs`, `npm`, `ripgrep`, optional Python packages such as `python-telegram-bot` and data-analysis helpers such as `pandas` when agent/runtime scripts actually import them.
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
   - Example:
     ```bash
     uv pip install --python /usr/local/lib/hermes-agent/venv/bin/python python-telegram-bot
     /usr/local/lib/hermes-agent/venv/bin/python -c 'import telegram; print(telegram.__version__)'
     ```

5. Let Hermes auto-fix its own command/path issues.
   - Run `hermes doctor --fix` after installing dependencies.
   - This can repair items like a missing `~/.local/bin/hermes` symlink.

6. Verify with both diagnostics and live smoke tests.
   - Re-run `hermes doctor`.
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
