# Messaging attachment smoke tests

Use this reference when validating whether Hermes can deliver a file attachment through a gateway platform such as Discord.

## Minimal test pattern

1. Create a tiny deterministic throwaway file under `/tmp`.
2. Send it with the messaging tool using a `MEDIA:/absolute/path` line in the message body.
3. Verify the returned delivery handle: platform, chat/channel ID, and message ID.
4. If the platform was recently reconfigured, retry once after the gateway reconnects or the home channel is refreshed.

Example payload shape:

```text
Hermes Discord file upload test
If you can see this attachment, file delivery is working.
```

Example send shape:

```text
send_message(
  target='discord:<channel_id>',
  message='Testing Discord file upload from Hermes.\n\nMEDIA:/tmp/hermes-discord-file-test.txt'
)
```

A successful Discord result includes a message ID, for example:

```json
{
  "success": true,
  "platform": "discord",
  "chat_id": "<channel_id>",
  "message_id": "<discord_message_id>"
}
```

## Interpreting failures

- Discord `403 Missing Access` means the bot token is valid enough to reach Discord, but the bot cannot access the configured channel, the channel/home ID is stale, or the gateway has not fully reconnected. Check permissions/home channel and retry after reconnect.
- `send_message(action='list')` may return no discovered channels even when a direct configured channel send later works; do not treat an empty list alone as final failure.
- Report setup gaps as setup gaps, not as durable claims that the messaging/file tool is broken.

## Reporting

Keep the final report concise:

- file path created
- target platform/channel
- success/failure
- returned message ID on success
- concrete permission/config next step on failure
