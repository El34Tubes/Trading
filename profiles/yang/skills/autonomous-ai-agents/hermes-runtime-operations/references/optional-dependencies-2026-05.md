# Optional Dependency Install + Verification Pattern (2026-05)

This reference captures a reusable Hermes runtime cleanup pattern. It is not a record of a permanent environment state.

## Situation

`hermes doctor` reported optional/system dependency gaps after a runtime validation pass. The useful learning is the sequence:

1. Install missing OS-level dependencies.
2. Install optional Python packages into the Hermes runtime venv, not the system Python.
3. Run `hermes doctor --fix` for Hermes-managed path repairs.
4. Re-run doctor and a live smoke test.

## Commands that worked

Ubuntu/Debian packages:

```bash
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs npm ripgrep
node --version
npm --version
rg --version | head -1
```

Hermes runtime venv package install:

```bash
uv pip install --python /usr/local/lib/hermes-agent/venv/bin/python python-telegram-bot
/usr/local/lib/hermes-agent/venv/bin/python - <<'PY'
import telegram
print('python-telegram-bot import ok:', getattr(telegram, '__version__', 'unknown'))
PY
```

Hermes auto-fix:

```bash
hermes doctor --fix
```

In the observed cleanup, this created the missing CLI symlink:

```text
~/.local/bin/hermes -> /usr/local/lib/hermes-agent/venv/bin/hermes
```

## Verification examples

Re-run diagnostics:

```bash
hermes doctor
```

Expected improvements after installing Node/ripgrep/python-telegram-bot include checks like:

```text
✓ python-telegram-bot (optional)
✓ ripgrep (rg) (faster file search)
✓ Node.js
✓ agent-browser (Node.js) (browser automation)
✓ Playwright Chromium (browser engine)
```

Browser smoke test:

- Navigate to `https://example.com`.
- Confirm title `Example Domain` and a small page snapshot.

## Pitfalls

- Do not install optional Python packages into whichever `python3` happens to be on PATH; Hermes may run from its own venv.
- Do not call unconfigured credential-backed tools “broken.” Report them as requiring API keys/OAuth/provider setup.
- Do not preserve temporary failure claims after a dependency install fixes them. Capture the fix and verification pattern instead.
