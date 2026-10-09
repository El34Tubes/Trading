# Wolfy concise progress audit — 2026-07-10

Use when the user asks a broad status question like “how are we progressing” and wants a concrete Wolfy state snapshot, not reassurance.

## Trigger

User asks for progress/state with no specific subsystem named.

## Effective audit sequence

1. Load the scheduled market research skill first.
2. Check live clock/timezone so freshness is anchored.
3. Inspect default-profile cron state (`hermes --profile default cron list --all`) and report active/paused counts plus last-run health for the visible loops.
4. Run the usage-limit watchdog directly. Silent output means no active production-provider quota block; do not treat stale historical 429 lines as current blockage.
5. Run `/root/.hermes/wolfy/visible_progress_ledger.py --format markdown` and use its tables as the primary source of truth.
6. If needed, query Postgres directly for recent `agent_runs` and task counts, but avoid schema guesses; first inspect or use known current columns (`agent_name`, `status`, `started_at`, `summary`, `error_message`).
7. Final answer should be compact and concrete: automation health, data rows/freshness, historical-depth coverage, signals/setups, strategy gates, paper-trade/accountability state, and one next build target.

## Wording pattern that worked

Start with the truth in one line:

> Progress is real, but we are still in build/validation/watch-only mode — not paper-trading actionable setups yet.

Then use short tables:

- `Area | Current state`
- `Strategy | Status | Latest OOS result | Gate`

Close with:

- The loop is alive if cron jobs are active and recent runs are OK.
- The blocker is strategy approval/validation if `setups=0` and all strategies are `research_only`.
- The next target should be one concrete build item, e.g. finish tiered EOD data coverage/backfill before broader OOS validation.

## Pitfalls

- Do not imply lack of setups means the system failed. Under Hermes-EOD, `0 setups` is correct when no strategy is approved.
- Do not over-explain every job. The user wants measurable progress, not a narrative of the architecture.
- Do not say “candidate is approved” or treat research-only/candidate signals as actionable capital setups.
- Avoid ad-hoc SQL against guessed columns; the current `agent_runs` agent column is `agent_name`, not `agent`.
