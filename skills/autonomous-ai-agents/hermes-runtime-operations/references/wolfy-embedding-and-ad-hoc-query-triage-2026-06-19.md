# Wolfy embedding + ad-hoc query triage (2026-06-19)

Use this when Mike/Wolfy operations context shows a small embedding gap, stale cron `Next run` timestamps, or warning tails from Jonah-created `tmp_*.py` probes.

## Lessons

1. **Embedding sync can close a gap silently.** If pre-run context shows `knowledge_chunks` total vs embedded mismatch, run the no-agent embedding wrapper, then re-query Postgres directly:
   ```bash
   /usr/local/lib/hermes-agent/venv/bin/python /root/.hermes/scripts/wolfy_embed_knowledge_chunks.py
   psql -d wolfy -P pager=off -c "select count(*) total, count(embedding) embedded, count(*)-count(embedding) missing from knowledge_chunks;"
   ```
   Empty stdout from the wrapper is healthy. Trust the follow-up count, not the stale pre-run snapshot.

2. **Stale cron `Next run` alone is not a stuck scheduler.** Around a just-due job, `hermes cron status` or `cron list` may still show the due timestamp while the gateway is between ticks. Cross-check session/output creation and wait/poll only if needed before reporting scheduler trouble.

3. **Jonah `tmp_*.py` warnings are triage leads, not durable infra failures.** Research agents often create scratch probes with SQL placeholder mistakes (`%M` in psycopg strings, missing aliases in exploratory `select *`, etc.). Before patching schema or wrappers, rerun the exact scratch script or reproduce the query. If core smokes pass and the warning is an ad-hoc research probe, report it as non-durable/no safe global repair rather than inventing a compatibility alias.

4. **Use operations smokes to bound severity.** A healthy run should include: Postgres requirements guard, usage watchdog silent run, safe autorepair silent run, stale coordination cleanup silent run, agent coordination counts (`0` stale started, `0` synthetic smoke blockers, `0` duplicate-claim noise), and Kanban check for open Mike cards.

## Reporting pattern

Concise table sections work well:

- Fixed: only real changes or state changes verified after a command.
- Verified: guards/smokes with actual counts.
- Remaining/blockers: setup gaps and non-durable triage leads separated from active failures.
- Next autonomous action: one sentence.
