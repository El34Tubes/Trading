# Mike active-tick budget-gate and bounded backfill advance (2026-07-08)

Context: Mike ops cron ran while several default-profile no-agent jobs were just due. `hermes cron status` showed a stale `Next run` timestamp, but the global cron tick lock was freshly touched by the active Mike LLM cron session. Treat this as an active-tick artifact until it persists after the LLM run exits.

Useful verification pattern:

1. Check current budget state directly:
   - `python3 /root/.hermes/wolfy/guardian/budget_gate.py`
   - If it prints `BUDGET=block ...`, verify LLM cron context scripts wake-gate before spending tokens.
2. Smoke both budget paths for every LLM context script using simulation env vars:
   - Block path: `WOLFY_CONTEXT_SMOKE=1 WOLFY_BUDGET_SIMULATED_TOKENS_TODAY=999999 WOLFY_BUDGET_IGNORE_AUTH=1 python3 <context.py>`
   - The final non-empty stdout line must be JSON: `{"wakeAgent": false, "reason": "budget"}`.
   - OK path: `WOLFY_CONTEXT_SMOKE=1 WOLFY_BUDGET_SIMULATED_TOKENS_TODAY=0 WOLFY_BUDGET_SIMULATED_HEADROOM_PCT=100 WOLFY_BUDGET_IGNORE_AUTH=1 python3 <context.py>`
   - The script should load deterministic context and avoid opening `agent_runs`/claiming tasks in smoke mode.
3. If a just-due no-agent job is safe and bounded, manually running its exact cron script can be an acceptable smoke/advance step while the active tick is occupied.
   - Example: `/root/.hermes/scripts/wolfy_tiered_backfill_bounded.py` advanced mid-cap coverage by a few tickers and exited 0.
   - Report real DB/state deltas (loaded/missing counts, tickers advanced, exit code) rather than claiming scheduler completion.
4. Recheck core invariants after manual advance:
   - Postgres requirements guard OK.
   - `stale_started_runs=0`.
   - Recent `duplicate-or-already-claimed` noise is 0.
   - Autorepair second run silent.
   - Usage watchdog silent.
5. If no durable fix was needed but real state advanced, deliver a concise report. Use `[SILENT]` only when there is genuinely no new fix, blocker, or state delta.

Pitfall: Do not classify an old weekly `HTTP 429` last_error as active failure if the job remains active, is not currently due, and budget wake-gates now block token spend safely.