# Wolfy config guardian profile-home pinning — 2026-07-03

## Trigger

Mike's profile-scoped environment repair cron invoked the Wolfy config guardian wrapper with a profile-scoped `HERMES_HOME` (for example `/root/.hermes/profiles/mike`). The guardian is intended to protect the production/default Hermes files under `/root/.hermes`, especially `config.yaml` and `cron/jobs.json`.

## Symptom

A direct wrapper smoke under Mike's inherited environment failed while the same guardian worked when invoked with the production home:

```text
FileNotFoundError: snapshot missing cron/jobs.json: /root/.hermes/profiles/mike/wolfy/guardian/known_good/<stamp>
```

This meant the guardian was searching for snapshots/protected files under the Mike profile instead of the production/default Hermes home.

## Safe repair pattern

Pin the cron-facing wrapper to the production home explicitly:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /root/.hermes
exec python3 /root/.hermes/wolfy/guardian/config_guardian.py --home /root/.hermes
```

Do **not** change the guardian's protected file list or create profile-local fake `cron/jobs.json` snapshots just to satisfy the smoke. The production/default files are the real protected assets.

## Verification

Run the wrapper from a simulated profile-scoped environment and verify it still checks the global/default config and cron state:

```bash
HERMES_HOME=/root/.hermes/profiles/mike bash /root/.hermes/scripts/wolfy_config_guardian.sh
```

Expected healthy output:

```text
GUARDIAN=ok checks=config_yaml_ok;optimizer_enabled;hermes_cron_list_ok;no_probation
```

Also verify:

```bash
bash -n /root/.hermes/scripts/wolfy_config_guardian.sh
python3 -m py_compile /root/.hermes/wolfy/guardian/config_guardian.py
/root/.hermes/scripts/mike_safe_autorepair.py >/tmp/autorepair1.out
/root/.hermes/scripts/mike_safe_autorepair.py >/tmp/autorepair2.out
```

The second autorepair run should be silent. If the autorepair script owns wrapper sync, patch the canonical global source first so profile copies do not overwrite the fix.
