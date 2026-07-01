#!/usr/bin/env bash
set -euo pipefail
cd /root/.hermes
exec python3 /root/.hermes/wolfy/guardian/config_guardian.py
