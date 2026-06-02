# Profile autorepair self-sync pattern

Session: 2026-06-02 Mike Wolfy operations triage.

## Trigger

Use this when a Hermes/Wolfy operations profile has a script-only autorepair job that keeps global/profile wrappers synchronized, but profile-scoped diagnostics or handoffs may invoke the autorepair script itself.

## Lesson

Wrapper sync must include the autorepair script itself. A global cron job can be healthy while `python3 /root/.hermes/profiles/<profile>/scripts/mike_safe_autorepair.py` fails because the profile copy was never created. This is wrapper drift, not a broken runtime.

## Safe repair pattern

1. Update the global canonical autorepair script, e.g. `/root/.hermes/scripts/mike_safe_autorepair.py`.
2. Add the autorepair script name to every profile sync allowlist that may run ops diagnostics:
   - Mike profile operations scripts.
   - Clerky/admin profile scripts if Clerky audits or summarizes operations handoffs.
3. Run the global autorepair once so it copies itself into profile script directories.
4. Verify each layer directly:
   ```bash
   python3 /root/.hermes/scripts/mike_safe_autorepair.py
   python3 /root/.hermes/profiles/mike/scripts/mike_safe_autorepair.py
   python3 /root/.hermes/profiles/clerky/scripts/mike_safe_autorepair.py
   ```
5. Verify nearby no-agent helpers and smoke tests, not just cron status:
   ```bash
   python3 /root/.hermes/wolfy/check_postgres_requirements.py
   python3 -m pytest /root/.hermes/wolfy/test_agent_coordination_smoke.py /root/.hermes/wolfy/tests/test_embed_knowledge_chunks.py -q
   python3 /root/.hermes/wolfy/wolfy_usage_limit_watchdog.py
   python3 /root/.hermes/wolfy/wolfy_capture_usage_snapshot.py
   python3 /root/.hermes/wolfy/wolfy_embed_knowledge_chunks.py
   ```

## Reporting nuance

If recent logs show old SQL/test errors, rerun the relevant tests first. Treat log tails as leads, not current truth. If the rerun passes, report the verification and do not invent a stale fix.
