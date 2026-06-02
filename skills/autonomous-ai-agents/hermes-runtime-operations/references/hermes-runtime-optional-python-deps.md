# Hermes runtime optional Python dependencies

Use this when a live Hermes cron/job script fails with `ModuleNotFoundError` for an optional Python package even though system Python can import it.

## Durable lesson

Hermes cron and agent tools may run under the Hermes runtime venv, commonly:

```bash
/usr/local/lib/hermes-agent/venv/bin/python
```

Installing a package into OS Python with `apt-get install python3-...` can be useful for scripts invoked with `/usr/bin/python3`, but it does **not** make the package available to Hermes' venv. For Hermes runtime failures, install into the venv directly.

## Verification / fix pattern

```bash
# Check which Python the live Hermes context uses
which python3
python3 - <<'PY'
import sys
print(sys.executable)
PY

# Install optional Python packages into the Hermes runtime venv
uv pip install --python /usr/local/lib/hermes-agent/venv/bin/python beautifulsoup4 lxml html5lib

# Verify with the same runtime
/usr/local/lib/hermes-agent/venv/bin/python - <<'PY'
import bs4, lxml, html5lib
print('bs4', bs4.__version__)
print('lxml', lxml.__version__)
PY
```

## Example from Wolfy operations

A Mike autonomous triage run saw `ModuleNotFoundError: No module named 'bs4'` from a Wolfy helper. `apt-get install python3-bs4` made `/usr/bin/python3` work, but Hermes' venv still failed. Installing `beautifulsoup4 lxml html5lib` via `uv pip install --python /usr/local/lib/hermes-agent/venv/bin/python ...` fixed the live Hermes runtime path.