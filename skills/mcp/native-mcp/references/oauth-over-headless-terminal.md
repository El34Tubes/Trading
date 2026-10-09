# MCP OAuth over headless / non-interactive terminals

Session-derived pattern from connecting Robinhood's HTTP MCP endpoint (`https://agent.robinhood.com/mcp/trading`) with OAuth 2.1 PKCE.

## Symptom

Running an OAuth-backed MCP command through an agent tool shell may fail even with tool-level PTY enabled:

```text
MCP OAuth for '<server>': non-interactive environment and no cached tokens found.
Run `hermes mcp login <server>` interactively first to complete initial authorization.
```

`hermes mcp test <server>` will continue to fail until token files exist under the profile's MCP token store.

## Working pattern

From the user's real shell, run the login under `script` to guarantee Hermes sees a TTY:

```bash
script -q -c 'hermes mcp login <server>' /dev/null
```

For Robinhood Trading MCP specifically:

```bash
script -q -c 'hermes mcp login robinhood_trading' /dev/null
```

Then:

1. Open the printed OAuth URL in a browser.
2. Approve access.
3. If the browser redirects to `http://127.0.0.1:<port>/callback` and fails because the browser is local but Hermes is on a remote/headless host, copy the full address-bar URL.
4. Paste the full redirect URL (or its `?code=...&state=...` query string) into the waiting terminal prompt.
5. Verify with:

```bash
hermes mcp test <server>
```

## Pitfalls

- Do not keep re-running `hermes mcp test` before OAuth login completes; it only confirms that cached tokens are missing.
- OAuth URLs are attempt-specific: if the command times out, restart login and use the fresh URL/state.
- If no browser callback can reach the remote listener, paste-back is usually easier than SSH port forwarding.
- After successful test, start a new Hermes session or `/reload-mcp` so newly discovered MCP tools enter the tool list.
