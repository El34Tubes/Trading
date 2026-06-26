# Wolfy daily optimization planner pattern — 2026-06-19

Use this when a scheduled Wolfy optimization/implementation job needs to make visible progress without stepping on live market/report jobs.

## Proven safe sequence

1. Load `hermes-agent`, `hermes-runtime-operations`, and `scheduled-market-research-reports`.
2. Snapshot before touching files:
   - `date -Is`
   - `git -C /root/.hermes status --short`
   - `hermes --profile default cron list --all`
   - `hermes --profile default cron status`
   - relevant process list for `hermes|wolfy|cron|python`
   - recent gateway/cron failures.
3. Check conflicts explicitly:
   - Avoid market/report windows.
   - Avoid editing scripts invoked by no-agent jobs due in the next few minutes.
   - If an LLM/report job is paused due usage limits, do not treat script-only backend jobs as stopped.
4. Maintain `/root/.hermes/wolfy/optimization_todo.md` as a durable TODO/impact-plan ledger.
5. Select at most two bounded optimizations; implement only low/medium-risk changes within the two-file throttle.
6. Prefer read-only deterministic status/reporting helpers over LLM-heavy synthesis.
7. Verify with compile/smoke output and summarize exact files changed. Do not commit unless asked.

## Useful bounded optimization discovered

A read-only `visible_progress_ledger.py` helper is a high-value first optimization when the user wants visible Wolfy progress. It should collect deterministic facts from Postgres and cron without writes:

- data freshness: latest `prices`/`features` dates and ticker counts;
- scanner freshness: latest run, latest data date, candidate count;
- signal/setup status: latest signal date/counts, setup counts, open positions;
- strategy gates: `research_only` / `candidate` / `approved`, OOS fields, and explicit "candidate is not approved" wording;
- blockers: recent `agent_runs` blocked/error rows;
- next action: one concrete build target.

Keep the output Markdown-table friendly for the user, and offer JSON mode for scripts. This preserves the EOD constitution: no live trading, no auto-execution, no approval promotion, and no setup proposals without an approved strategy.

## Verification notes

- Verify helper scripts with `python3 -m py_compile` and both JSON and Markdown smoke runs.
- Avoid `python script.py --json | python3 -c ...` because Tirith may flag pipe-to-interpreter; write JSON to `/tmp/...json` and inspect that file with a separate interpreter call instead.
- If a smoke query hits alias drift, patch the helper to use canonical Postgres columns rather than adding new aliases unless a real consumer requires them. Example: `agent_runs` has `summary`, `result_summary`, `ended_at`, `completed_at`, and `started_at`; do not assume `description` or `created_at` exist there.
