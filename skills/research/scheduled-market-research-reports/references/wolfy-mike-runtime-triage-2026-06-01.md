# Wolfy Mike runtime triage note — 2026-06-01

Operational details from a Mike autonomous environment repair run. Use as a reference when future Wolfy cron jobs fail due to wrapper drift, optional Python imports, or stale coordination rows.

## What was fixed

- Missing HTML parser dependency was fixed in the Hermes runtime venv, not just OS Python:
  ```bash
  uv pip install --python /usr/local/lib/hermes-agent/venv/bin/python beautifulsoup4 lxml html5lib
  /usr/local/lib/hermes-agent/venv/bin/python -c 'import bs4, lxml, html5lib; print(bs4.__version__, lxml.__version__)'
  ```
- A legacy alpha-search wrapper path was restored for backward compatibility:
  ```bash
  /root/.hermes/scripts/wolfy-alpha-search-report.sh
  ```
  Wrapper content delegates to:
  ```bash
  python3 /root/.hermes/wolfy/alpha_search_context.py "$@"
  ```
- `mike_safe_autorepair.py` was expanded to preserve that legacy wrapper and sync cron-usage wrapper scripts into Mike and Clerky profile script directories.

## Verification commands used

```bash
python /root/.hermes/wolfy/check_postgres_requirements.py
python3 -m pytest -q test_agent_coordination_smoke.py tests/test_embed_knowledge_chunks.py test_alpha_search_pipeline.py test_insider_buying.py test_suspicious_activity.py test_yang_technical_reviews.py test_stocktwits_social_scanner.py
python3 /root/.hermes/wolfy/embed_knowledge_chunks.py
python3 /root/.hermes/wolfy/cleanup_stale_agent_coordination.py
python3 /root/.hermes/wolfy/capture_usage_snapshot.py
/root/.hermes/scripts/wolfy-alpha-search-report.sh >/tmp/wolfy-alpha-wrapper.out
```

Expected healthy result: tests pass, script-only helpers stay silent, alpha wrapper emits context output, and `knowledge_chunks` embedding count equals total count.

## Coordination note

A currently running Mike cron session can legitimately appear as `agent_runs.status='started'`; do not mark it stale unless it exceeds the watchdog threshold. A smoke-test run inserted by calling `alpha_search_context.py` directly should be completed/closed if it only exists to verify wrapper health.