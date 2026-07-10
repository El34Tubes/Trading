# Wolfy usage-limit watchdog: noisy dedupe and chat-text false positives (2026-07-06)

## Trigger

Use this when the Wolfy/Mike usage-limit watchdog (`wolfy_usage_limit_watchdog.py`, job `1eec7c61b1d9`) keeps delivering quota/rate-limit alerts after the provider has already cleared, or when a user asks whether the system is rate limited and the watchdog later reports that user text as evidence.

## Observed failure mode

The watchdog is a `no_agent` cron job and runs regardless of whether LLM quota is available. Healthy no-limit runs should emit empty stdout and therefore deliver nothing.

A noisy alert loop can happen even when active model calls are succeeding if any of these are true:

1. Log scanning treats generic lines such as `credential pool: no available entries (all exhausted or empty)` as quota evidence. The word `exhausted` alone is too broad.
2. Log scanning matches user/chat text such as `Are we rate limited` in gateway or conversation-turn logs. User questions are not provider-health evidence.
3. The `seen` dedupe set is sorted before truncation. Lexicographic trimming can drop fresh low-valued hashes, causing the same old 429 log lines to be rediscovered every tick.
4. The seen cap is too small for the current tail window, so old high-volume 429 bursts churn out of the retained state.

## Safe repair pattern

Patch the canonical global script first, then sync copies:

- `/root/.hermes/scripts/wolfy_usage_limit_watchdog.py`
- `/root/.hermes/wolfy/wolfy_usage_limit_watchdog.py`
- `/root/.hermes/profiles/mike/scripts/wolfy_usage_limit_watchdog.py`
- `/root/.hermes/profiles/clerky/scripts/wolfy_usage_limit_watchdog.py`

Durable code changes:

- Remove bare/generic `exhausted` from the usage-limit regex. Keep explicit quota/rate-limit terms such as `usage_limit_reached`, `HTTP 429`, `too many requests`, `quota exceeded`, etc.
- Add a helper that filters out gateway inbound-message lines and conversation-turn `msg=` lines before applying the rate-limit regex.
- Preserve `seen` digests in recency/insertion order; do not sort before truncating.
- Use a seen cap comfortably larger than the log tail scan window, e.g. `SEEN_LIMIT = 20000` when scanning several thousand lines across multiple logs.

## Verification

Run:

```bash
python3 -m py_compile \
  /root/.hermes/scripts/wolfy_usage_limit_watchdog.py \
  /root/.hermes/wolfy/wolfy_usage_limit_watchdog.py \
  /root/.hermes/profiles/mike/scripts/wolfy_usage_limit_watchdog.py \
  /root/.hermes/profiles/clerky/scripts/wolfy_usage_limit_watchdog.py

python3 /root/.hermes/scripts/wolfy_usage_limit_watchdog.py >/tmp/watchdog1.out
python3 /root/.hermes/scripts/wolfy_usage_limit_watchdog.py >/tmp/watchdog2.out
wc -c /tmp/watchdog1.out /tmp/watchdog2.out
```

Expected result after a one-time flush of previously undeduped old evidence:

- second run is `0` bytes when no new provider-limit event exists;
- state has `limited_active: false` and empty `paused_llm_jobs` when provider calls are succeeding;
- `hermes --profile default chat -Q -m gpt-5.5 -q '...reply OK'` succeeds if using a live model smoke.

## Reporting guidance

When explaining this to the user, distinguish two separate questions:

- **Does the watchdog run when not limited?** Yes. It is a `no_agent` scheduled script and should run silently when healthy.
- **Does it alert when not limited?** It should not, except for a one-time flush of previously unseen old evidence after a dedupe fix or a genuine pause/resume transition.
