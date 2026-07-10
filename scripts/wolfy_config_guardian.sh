#!/usr/bin/env bash
set -euo pipefail
cd /root/.hermes
# Pin the guardian to the production/default Hermes home.  Mike cron runs with
# a profile-scoped HERMES_HOME, and the guardian protects the global/default
# cron/config files that own Wolfy production jobs.
exec python3 /root/.hermes/wolfy/guardian/config_guardian.py --home /root/.hermes
