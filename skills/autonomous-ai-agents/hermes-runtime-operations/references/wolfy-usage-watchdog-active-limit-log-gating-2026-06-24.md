# Wolfy usage-watchdog active-limit log gating — 2026-06-24

## Context
Mike ops found a recurring pattern where an LLM-driven cron job (`Wolfy daily optimization planner and implementer`, job `92f31b95fccc`) failed with OpenAI Codex `HTTP 429 usage_limit_reached`, while the script-only usage watchdog stayed quiet because `hermes --profile default auth list openai-codex` did not surface the active limit.

## Durable lesson
For script-only usage/quota watchdogs, auth health alone may be insufficient. If Hermes logs contain same-day `usage_limit_reached` lines with a provider reset field, use the reset timestamp to determine whether the limit is still active:

- Treat `resets_at > time.time()` as active provider-limit evidence.
- Treat `resets_in_seconds > 0` as active only when no `resets_at` is available.
- Do **not** treat stale same-day 429 lines as active once `resets_at` has passed; otherwise the watchdog can keep jobs paused after the provider resets.

## Safe gating behavior
When an active limit is detected, pause all LLM-driven Wolfy/Mike jobs that would spend model tokens and create repeated quota failures, including planner/implementer jobs. Leave script-only jobs active:

- storage watchdog
- usage watchdog
- embedding sync
- stale coordination cleanup
- safe autorepair
- deterministic scanner/EOD ingest/features jobs

When the reset has passed and auth/log checks no longer indicate an active limit, auto-resume only the jobs the watchdog paused.

## Verification pattern
1. Compile the watchdog and autorepair scripts.
2. Run the watchdog once; it should pause/resume only on state transition.
3. Run the watchdog again; it should be silent if nothing changed.
4. Run autorepair twice; second run should be silent.
5. Verify `hermes --profile default cron list --all` shows expected active/paused state.
6. Verify Postgres coordination remains clean (`stale_started_runs=0`, duplicate claim noise remains 0) and embedding coverage is not degraded.

## Pitfall
Do not add schema aliases for one-off LLM scratch-query mistakes unless a real durable consumer requires the column. In this session, Jonah ad-hoc psycopg errors were caused by bad scratch SQL (`%S` placeholder, nonexistent `scanner_result_id`) and the tasks completed successfully afterward; no schema migration was warranted.
