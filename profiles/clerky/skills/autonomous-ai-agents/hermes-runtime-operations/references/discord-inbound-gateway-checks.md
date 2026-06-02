# Discord inbound gateway checks

Use this reference when outbound Discord delivery works but the user asks whether a message sent in Discord made it back into Hermes.

## What to distinguish

There are three separate states:

1. Discord channel received/sent the message.
2. The Hermes Discord gateway observed the message.
3. Hermes accepted the message into an agent session and processed it.

A message can satisfy (1) and (2) but fail (3), commonly because the Discord user is not authorized or because the message did not meet mention/free-response rules.

## Practical verification pattern

- If API credentials are available, query recent Discord channel messages directly through Discord's REST API to confirm the exact message, author, timestamp, and message id. Do not print bot tokens.
- Check `~/.hermes/state.db` for new messages after the Discord timestamp. A processed gateway message should appear as a user message, often with a `platform_message_id` or a gateway-created session/source. Absence from state means it did not become an accepted Hermes request.
- Check `~/.hermes/logs/gateway.log` around the message timestamp.

Useful log outcomes:

- `Flushing text batch ... discord:thread:<id>...` means the Discord gateway observed/batched the inbound text.
- `Unauthorized user: <id> (...) on discord` means Hermes saw the message but rejected it before agent processing.
- Reconnect/timeouts before the message timestamp indicate the gateway may not have been connected when the message was sent.

## Config gates to inspect

- `discord.require_mention: true` means ordinary channel messages are ignored unless they mention the bot.
- `discord.free_response_channels` controls channels where plain messages can be processed without mention.
- Discord user authorization / pairing controls whether a seen message is accepted. If logs show `Unauthorized user`, tell the user the message reached the gateway but was rejected as unauthorized, and use the platform's normal authorization/pairing flow before retesting.

## Fixing Discord user authorization

When a Discord message is present in channel history and gateway logs show `Unauthorized user: <discord_user_id> (...) on discord`, authorize the user before retesting. Do not frame this as a Discord channel permission problem unless Discord API delivery/read itself is failing.

Fastest targeted fix, in `~/.hermes/.env`:

```bash
DISCORD_ALLOWED_USERS=<discord_user_id>
```

If the variable already exists, append the ID comma-separated:

```bash
DISCORD_ALLOWED_USERS=<existing_id>,<discord_user_id>
```

Less-safe broad fix for private/test servers only:

```bash
DISCORD_ALLOW_ALL_USERS=true
```

Pairing-code path, if a pending code exists:

```bash
hermes pairing list
hermes pairing approve discord <CODE>
```

Always restart the gateway after changing `.env` authorization variables:

```bash
hermes gateway restart
```

If the user also wants plain channel messages without mentioning the bot, configure the channel gate separately:

```bash
hermes config set discord.free_response_channels <channel_id>
# or globally relax mention requirement:
hermes config set discord.require_mention false
hermes gateway restart
```

Best-practice test-channel setup is: add the specific user to `DISCORD_ALLOWED_USERS`, add the channel to `discord.free_response_channels`, restart gateway, then send a fresh user-authored message and verify all three layers again.

When you are asked to make the change yourself, perform the file/config edits and restart immediately, then verify the gateway reconnected before asking for a fresh inbound message:

```bash
# add/append the user id without printing secrets
python3 - <<'PY'
from pathlib import Path
p = Path.home() / '.hermes' / '.env'
user_id = '<discord_user_id>'
key = 'DISCORD_ALLOWED_USERS'
text = p.read_text() if p.exists() else ''
lines = text.splitlines()
out = []
found = False
for line in lines:
    if line.strip().startswith(key + '='):
        found = True
        k, v = line.split('=', 1)
        vals = [x.strip() for x in v.strip().strip('"').strip("'").split(',') if x.strip()]
        if user_id not in vals and '*' not in vals:
            vals.append(user_id)
        out.append(f'{key}={",".join(vals)}')
    else:
        out.append(line)
if not found:
    if out and out[-1].strip():
        out.append('')
    out.append(f'{key}={user_id}')
p.write_text('\n'.join(out) + '\n')
p.chmod(0o600)
PY
hermes config set discord.free_response_channels <channel_id>
hermes gateway restart
hermes gateway status
```

A bot-authored outbound test message proves Discord sending still works after restart, but it does not prove inbound human authorization. The final confirmation requires a new message authored by the allowed Discord user, then checking state/logs for processing rather than `Unauthorized user`.

## Reporting language

Be precise:

- “Discord received it” = found via channel API/history.
- “Gateway saw it” = found in gateway logs, e.g. text batching.
- “Hermes processed it” = found in session state and/or a bot response was produced.

Avoid saying simply “Hermes received it” unless all three layers are clear; otherwise state the deepest confirmed layer and the blocker.
